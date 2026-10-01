"""Telegram chat. One private conversation drives the PC."""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from openagent.agent import AgentEvents, fresh_history, run_agent
from openagent.config import Settings
from openagent.desktop import Desktop
from openagent.format_tg import (
    chunks,
    render_confirm,
    render_error,
    render_final,
    render_help,
    render_caption,
    render_progress,
    render_queued,
    render_started,
    render_stopped,
    render_welcome,
)
from openagent.llm import OpenRouter

log = logging.getLogger("openagent.bot")


@dataclass
class Session:
    messages: list = field(default_factory=fresh_history)
    task: asyncio.Task | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    inbox: asyncio.Queue = field(default_factory=asyncio.Queue)
    confirms: dict = field(default_factory=dict)
    status: Message | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class App:
    def __init__(self, settings: Settings, desktop: Desktop, llm: OpenRouter) -> None:
        self.settings = settings
        self.desktop = desktop
        self.llm = llm
        self.sessions: dict[int, Session] = {}

    def session(self, user_id: int) -> Session:
        if user_id not in self.sessions:
            self.sessions[user_id] = Session()
        return self.sessions[user_id]

    def allowed(self, user_id: int) -> bool:
        return user_id in self.settings.allowed_user_ids


def build_router(app: App) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        if not _private(message):
            return
        user_id = message.from_user.id if message.from_user else 0
        await _send(message.bot, message.chat.id, render_welcome(user_id, app.allowed(user_id)))

    @router.message(Command("help"))
    async def help_cmd(message: Message) -> None:
        if not await _gate(app, message):
            return
        await _send(message.bot, message.chat.id, render_help())

    @router.message(Command("stop"))
    async def stop_cmd(message: Message) -> None:
        if not await _gate(app, message):
            return
        session = app.session(message.from_user.id)
        running = session.task is not None and not session.task.done()
        await _halt(session)
        if not running:
            await _send(message.bot, message.chat.id, "<i>Nothing is running.</i>")

    @router.message(Command("reset"))
    async def reset_cmd(message: Message) -> None:
        if not await _gate(app, message):
            return
        session = app.session(message.from_user.id)
        if session.task and not session.task.done():
            await _send(message.bot, message.chat.id, "<i>Send /stop first, then /reset.</i>")
            return
        session.messages = fresh_history()
        await _send(message.bot, message.chat.id, "<b>Reset</b>\n<i>Forgot the previous conversation. Send a new task.</i>")

    @router.message(F.text)
    async def on_text(message: Message) -> None:
        if not await _gate(app, message):
            return
        text = (message.text or "").strip()
        if not text:
            return
        if text.startswith("/"):
            await _send(message.bot, message.chat.id, "<i>Unknown command. See /help.</i>")
            return
        session = app.session(message.from_user.id)
        async with session.lock:
            running = session.task is not None and not session.task.done()
            if running:
                await session.inbox.put(text)
            else:
                session.cancel.clear()
                session.task = asyncio.create_task(_run(app, message, session, text))
        if running:
            await _send(message.bot, message.chat.id, render_queued())

    @router.callback_query(F.data == "stop")
    async def on_stop_button(query: CallbackQuery) -> None:
        if not _callback_ok(app, query):
            await query.answer("Not allowed")
            return
        await _halt(app.session(query.from_user.id))
        await query.answer("Stopped")

    @router.callback_query(F.data.startswith("y:") | F.data.startswith("n:"))
    async def on_confirm(query: CallbackQuery) -> None:
        if not _callback_ok(app, query):
            await query.answer("Not allowed")
            return
        token = (query.data or "")[2:]
        allow = (query.data or "").startswith("y:")
        future = app.session(query.from_user.id).confirms.get(token)
        if future is None or future.done():
            await query.answer("This prompt is closed")
            return
        future.set_result(allow)
        await query.answer("Allowed" if allow else "Cancelled")
        if query.message:
            try:
                await query.message.edit_reply_markup(reply_markup=None)
            except TelegramBadRequest:
                pass

    return router


async def _run(app: App, message: Message, session: Session, text: str) -> None:
    ui = ChatUI(message.bot, message.chat.id, session)
    try:
        await ui.started(text)
        events = AgentEvents(
            cancel=session.cancel,
            inbox=session.inbox,
            confirm=ui.confirm,
            progress=ui.progress,
            photo=ui.photo,
            final=ui.final,
            stopped=ui.stopped,
            fail=ui.fail,
        )
        await run_agent(app.settings, app.llm, app.desktop, session.messages, text, events)
    except asyncio.CancelledError:
        await ui.stopped()
    except Exception:
        log.exception("Task failed")
        await ui.fail("Something failed inside the agent. Check the log.")
    finally:
        await ui.clear_keyboard()
        async with session.lock:
            pending = _drain(session.inbox)
            if pending:
                session.cancel.clear()
                session.task = asyncio.create_task(_run(app, message, session, "\n".join(pending)))


def _drain(inbox: asyncio.Queue) -> list[str]:
    items: list[str] = []
    while True:
        try:
            item = inbox.get_nowait()
        except asyncio.QueueEmpty:
            break
        text = str(item).strip()
        if text:
            items.append(text)
    return items


def _private(message: Message) -> bool:
    return message.chat.type == ChatType.PRIVATE and message.from_user is not None


async def _gate(app: App, message: Message) -> bool:
    if not _private(message):
        return False
    user_id = message.from_user.id
    if app.allowed(user_id):
        return True
    await _send(message.bot, message.chat.id, render_welcome(user_id, False))
    return False


def _callback_ok(app: App, query: CallbackQuery) -> bool:
    user = query.from_user
    return user is not None and app.allowed(user.id)


async def _halt(session: Session) -> None:
    session.cancel.set()
    _drain(session.inbox)
    for future in list(session.confirms.values()):
        if not future.done():
            future.set_result(False)


def _stop_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Stop", callback_data="stop")]]
    )


def _confirm_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="Allow", callback_data=f"y:{token}"),
            InlineKeyboardButton(text="Cancel", callback_data=f"n:{token}"),
        ]]
    )


class ChatUI:
    def __init__(self, bot: Bot, chat_id: int, session: Session) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.session = session
        self.latest: Message | None = None
        self.latest_photo: Message | None = None
        self.card: tuple[int, int, str, str, str] = (0, 0, "", "", "")
        self._photo_size: tuple[int, int] = (0, 0)

    async def started(self, task: str) -> None:
        self.session.status = await _send(
            self.bot,
            self.chat_id,
            render_started(task),
            reply_markup=_stop_keyboard(),
        )

    async def progress(self, step: int, max_steps: int, narration: str, action: str, detail: str, result: str) -> None:
        self.card = (step, max_steps, narration, action, detail)
        if not result:
            body = render_progress(step, max_steps, narration, action, detail, "")
            await self._new_step(body)
            return
        if self.latest_photo is not None:
            caption = render_caption(step, max_steps, narration, action, detail, result, *self._photo_size)
            await self._edit_caption(self.latest_photo, caption)
            return
        body = render_progress(step, max_steps, narration, action, detail, result)
        if self.latest is not None:
            await self._edit_text(self.latest, body)
            return
        await self._new_step(body)

    async def photo(self, data: bytes, width: int, height: int) -> None:
        step, max_steps, narration, action, detail = self.card
        caption = render_caption(step, max_steps, narration, action, detail, "", width, height)
        self._photo_size = (width, height)
        if self.latest is not None:
            try:
                await self.latest.delete()
            except TelegramBadRequest:
                await self._strip_keyboard(self.latest)
            self.latest = None
        message = await self._send_photo(data, caption)
        if message is None:
            return
        self.latest_photo = message
        self.session.status = message

    async def final(self, text: str, footer: str) -> None:
        await self.clear_keyboard()
        for part in chunks(render_final(text, footer)):
            await _send(self.bot, self.chat_id, part)

    async def stopped(self, footer: str = "") -> None:
        await self.clear_keyboard()
        await _send(self.bot, self.chat_id, render_stopped(footer))

    async def fail(self, text: str, footer: str = "") -> None:
        await self.clear_keyboard()
        await _send(self.bot, self.chat_id, render_error(text, footer))

    async def confirm(self, command: str, reason: str) -> bool:
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        token = _token()
        self.session.confirms[token] = future
        await _send(
            self.bot,
            self.chat_id,
            render_confirm(command, reason),
            reply_markup=_confirm_keyboard(token),
        )
        try:
            return bool(await asyncio.wait_for(future, timeout=180))
        except asyncio.TimeoutError:
            return False
        finally:
            self.session.confirms.pop(token, None)

    async def clear_keyboard(self) -> None:
        await self._strip_keyboard(self.session.status)

    async def _new_step(self, body: str) -> None:
        await self._strip_keyboard(self.session.status)
        message = await _send(self.bot, self.chat_id, body, reply_markup=_stop_keyboard())
        self.latest = message
        self.latest_photo = None
        self.session.status = message

    async def _edit_text(self, message: Message, body: str) -> None:
        try:
            await message.edit_text(body, reply_markup=_stop_keyboard())
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                await message.edit_text(body, reply_markup=_stop_keyboard())
            except TelegramBadRequest:
                pass
        except TelegramBadRequest as exc:
            if "not modified" not in str(exc).lower():
                log.warning("Step edit failed: %s", exc)

    async def _edit_caption(self, message: Message, caption: str) -> None:
        try:
            await message.edit_caption(caption=caption, reply_markup=_stop_keyboard())
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                await message.edit_caption(caption=caption, reply_markup=_stop_keyboard())
            except TelegramBadRequest:
                pass
        except TelegramBadRequest as exc:
            if "not modified" not in str(exc).lower():
                log.warning("Caption edit failed: %s", exc)

    async def _send_photo(self, data: bytes, caption: str) -> Message | None:
        photo = BufferedInputFile(data, filename="screen.jpg")
        try:
            return await self.bot.send_photo(
                self.chat_id,
                photo,
                caption=caption,
                reply_markup=_stop_keyboard(),
            )
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            return await self.bot.send_photo(
                self.chat_id,
                BufferedInputFile(data, filename="screen.jpg"),
                caption=caption,
                reply_markup=_stop_keyboard(),
            )
        except TelegramBadRequest:
            log.exception("Could not send screenshot")
            return None

    async def _strip_keyboard(self, message: Message | None) -> None:
        if message is None:
            return
        try:
            await message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass


def _token() -> str:
    import secrets

    return secrets.token_hex(4)


async def _send(bot: Bot, chat_id: int, text: str, reply_markup=None) -> Message:
    try:
        return await bot.send_message(chat_id, text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "parse" not in str(exc).lower() and "entity" not in str(exc).lower():
            raise
        log.warning("HTML rejected, sending plain text: %s", exc)
        plain = _strip_tags(text)
        return await bot.send_message(chat_id, plain, reply_markup=reply_markup, parse_mode=None)
    except TelegramRetryAfter as exc:
        await asyncio.sleep(exc.retry_after)
        return await bot.send_message(chat_id, text, reply_markup=reply_markup)


def _strip_tags(text: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", text)


async def serve(settings: Settings, desktop: Desktop, llm: OpenRouter) -> None:
    app = App(settings, desktop, llm)
    bot = Bot(settings.telegram_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(app))
    log.info("Telegram polling started. Model %s", settings.model)
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
        await llm.close()
