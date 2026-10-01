"""The desktop loop. The model sees tools, not a script of clicks written ahead of time."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
from dataclasses import dataclass, field

from openctrl.config import Settings
from openctrl.driver import Desktop
from openctrl.screen import Shot
from openctrl.files import resolve_send_path
from openctrl.format_tg import humanize, one_line
from openctrl.llm import LLMError, OpenRouter
from openctrl.memory import Memory
from openctrl.safety import danger_reason
from openctrl.schedule import Schedule

log = logging.getLogger("openctrl.agent")

def _system(shell: str) -> str:
    return """You are OpenCtrl. You operate the user's own computer from Telegram. The user watches the screen and the chat.

Work in small steps.
- Prefer the accessibility tree: foreground, list_windows, focus_window, ui_tree, click_control, type_text, press_keys.
- Take a screenshot only when the tree has no usable control, the UI is custom-drawn, or you must see pixels. Do not screenshot every step.
- After a screenshot, the next message contains the image. Do not click, drag, or scroll in the same step as the screenshot. On the following step use coordinate_space "image". (0, 0) is the top-left of that image.
- ui_tree lines include screen coordinates like @x,y widthxheight. Those are screen pixels. Use coordinate_space "screen" only for those numbers.
- launch opens programs, files, folders, and URLs. To open a folder in Cursor without a prompt, call launch with target "cursor" and args set to the folder name or full path. A bare name is searched on the Desktop.
- When the user wants Cursor's AI to do the work, call cursor_prompt with the folder and the instruction. It opens the folder, focuses Cursor, opens the agent panel, pastes the text, and presses Enter. Do not click through the Cursor UI for that.
- send_file sends one file from this PC into the Telegram chat. Never send .env, keys, or password files.
- clipboard_set copies text to the clipboard. clipboard_get reads it.
- window minimizes, maximizes, restores, or moves a window to a monitor.
- Notes from earlier tasks are included with the user message. Use memory to save a folder, preference, or fact you will need again.
- schedule runs an instruction later, from 15 seconds up to 24 hours, while OpenCtrl is running.
- If a tool says the desktop is locked, stop. Do not keep calling tools.
- run_shell runs {shell} for files, settings, and text output. Do not use it to click a window.
- type_text pastes Unicode, including Bengali, into the focused control. Click the edit box first when it is not already focused.
- press_keys is only for chords and single keys: ctrl+s, alt+tab, win+e, enter, ctrl+shift+p. Never put a sentence in press_keys. On macOS, ctrl means Command.
- After an action, check the result with foreground or ui_tree before saying it worked. If a tool returns an error, change approach. Do not repeat the same failed call.
- When tool calls are present, put one short status sentence in the assistant content, in English. That sentence is shown in Telegram. No hidden plan, no markdown heading.
- When the task is finished or you are blocked, stop calling tools and write a clear summary in English: what changed, where things are, and what you need if you are blocked.
- Never invent passwords, codes, or confirmation prompts. If a secure desktop, UAC prompt, login, or lock screen is in the way, stop and ask the user.
- You only control this computer. Do not send the user's files or secrets anywhere except the Telegram chat they are already using.
""".format(shell=shell)


@dataclass
class ToolResult:
    text: str
    image: bytes | None = None
    width: int = 0
    height: int = 0


@dataclass
class RunStats:
    steps: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    cost_known: bool = False
    budget_blocks: int = 1


@dataclass
class AgentEvents:
    cancel: threading.Event
    inbox: asyncio.Queue
    confirm: callable = field(repr=False)
    progress: callable = field(repr=False)
    photo: callable = field(repr=False)
    final: callable = field(repr=False)
    stopped: callable = field(repr=False)
    fail: callable = field(repr=False)
    send_file: callable = field(repr=False)


def fresh_history(shell: str = "PowerShell") -> list[dict]:
    return [{"role": "system", "content": _system(shell)}]


async def run_agent(
    settings: Settings,
    llm: OpenRouter,
    desktop: Desktop,
    messages: list[dict],
    task: str,
    events: AgentEvents,
    memory: Memory | None = None,
    schedule: Schedule | None = None,
    user_id: int = 0,
    chat_id: int = 0,
    image: bytes | None = None,
    seed_cost: float = 0.0,
) -> None:
    _repair_tool_calls(messages)
    messages.append(_user_turn(task, memory.snapshot() if memory else "", image))
    if memory:
        memory.write("last_task", one_line(task, 300))
    stats = RunStats()
    if seed_cost > 0:
        stats.cost = seed_cost
        stats.cost_known = True
    try:
        desktop.push_awake()
        for step in range(1, settings.max_steps + 1):
            if events.cancel.is_set():
                await events.stopped(_footer(stats, stats.steps))
                return
            locked = await asyncio.to_thread(desktop.screen_locked)
            if locked:
                await events.final(locked, _footer(stats, stats.steps))
                return
            extra_cost = _pull_inbox(messages, events.inbox)
            if extra_cost:
                stats.cost += extra_cost
                stats.cost_known = True
            _prepare(messages)
            try:
                message, usage = await _complete(llm, messages, events.cancel, desktop.shell_name)
            except asyncio.CancelledError:
                await events.stopped(_footer(stats, stats.steps))
                return
            except LLMError as exc:
                await events.fail(str(exc), _footer(stats, stats.steps))
                return
            stats.prompt_tokens += int(usage.get("prompt_tokens") or 0)
            stats.completion_tokens += int(usage.get("completion_tokens") or 0)
            _add_cost(stats, usage)
            tool_calls = message.get("tool_calls") or []
            narration = one_line(_text(message.get("content")))
            messages.append(_assistant_record(message))
            if tool_calls and await _stop_for_budget(settings, stats, events):
                for call in tool_calls:
                    messages.append(_tool_message(call, "Stopped because the cost limit was reached."))
                return
            if not tool_calls:
                summary = _text(message.get("content")) or "Done."
                if memory:
                    memory.write("last_summary", one_line(summary, 500))
                await events.final(summary, _footer(stats, step))
                return
            stats.steps = step
            images: list[ToolResult] = []
            for index, call in enumerate(tool_calls):
                if events.cancel.is_set():
                    _close_calls(messages, tool_calls[index:], "Cancelled by the user.")
                    await events.stopped(_footer(stats, stats.steps))
                    return
                name, args = _parse_call(call)
                await events.progress(
                    step=step,
                    max_steps=settings.max_steps,
                    narration=narration or humanize(name, args),
                    action=name,
                    detail=_detail(name, args),
                    result="",
                )
                narration = ""
                try:
                    result = await _dispatch(
                        desktop,
                        events,
                        name,
                        args,
                        memory=memory,
                        schedule=schedule,
                        user_id=user_id,
                        chat_id=chat_id,
                        inbox=settings.root / "inbox",
                    )
                except Exception as exc:
                    log.exception("Tool %s failed", name)
                    result = ToolResult(text=f"Tool error: {exc}")
                messages.append(_tool_message(call, _cap(result.text, 9000)))
                if _desktop_locked(result.text):
                    _close_calls(messages, tool_calls[index + 1 :], "Stopped because the desktop is locked.")
                    await events.final(result.text, _footer(stats, stats.steps))
                    return
                if result.image:
                    images.append(result)
                    await events.photo(result.image, result.width, result.height)
                await events.progress(
                    step=step,
                    max_steps=settings.max_steps,
                    narration=humanize(name, args),
                    action=name,
                    detail=_detail(name, args),
                    result=result.text,
                )
            for result in images:
                messages.append(_image_message(result))
        await events.final(
            "Reached the step limit and stopped. Send another message to continue.",
            _footer(stats, settings.max_steps),
        )
    except Exception as exc:
        log.exception("Agent crashed")
        await events.fail(str(exc))
    finally:
        desktop.pop_awake()


def _repair_tool_calls(messages: list[dict]) -> None:
    index = 0
    while index < len(messages):
        message = messages[index]
        calls = message.get("tool_calls") if message.get("role") == "assistant" else None
        if not calls:
            index += 1
            continue
        needed = [call.get("id") or "" for call in calls]
        cursor = index + 1
        seen: set[str] = set()
        while cursor < len(messages) and messages[cursor].get("role") == "tool":
            seen.add(messages[cursor].get("tool_call_id") or "")
            cursor += 1
        for tool_id in needed:
            if tool_id in seen:
                continue
            messages.insert(
                cursor,
                {
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": "Interrupted before this tool finished.",
                },
            )
            cursor += 1
        index = cursor


def unpack_note(item) -> tuple[str, bytes | None, float]:
    if isinstance(item, str):
        return item, None, 0.0
    if isinstance(item, tuple) and len(item) == 3:
        text, image, cost = item
        picture = image if isinstance(image, (bytes, bytearray)) else None
        try:
            amount = float(cost or 0)
        except (TypeError, ValueError):
            amount = 0.0
        return str(text), picture, amount
    return str(item), None, 0.0


def combine_notes(items: list) -> tuple[str, bytes | None, float]:
    texts: list[str] = []
    image: bytes | None = None
    cost = 0.0
    for item in items:
        text, picture, extra = unpack_note(item)
        if text.strip():
            texts.append(text.strip())
        if picture:
            image = bytes(picture)
        cost += extra
    return "\n".join(texts), image, cost


def _pull_inbox(messages: list[dict], inbox: asyncio.Queue) -> float:
    items = []
    while True:
        try:
            items.append(inbox.get_nowait())
        except asyncio.QueueEmpty:
            break
    text, image, cost = combine_notes(items)
    if text or image:
        body = "New instruction while you are working:\n" + text
        messages.append(_user_turn(body, "", image))
    return cost


def _close_calls(messages: list[dict], calls: list, note: str) -> None:
    for call in calls:
        messages.append(_tool_message(call, note))


def _desktop_locked(text: str) -> bool:
    return "desktop is locked" in text.lower()


def _prepare(messages: list[dict]) -> None:
    _slim_images(messages)
    _strip_old_reasoning(messages)
    _trim(messages, keep=40)
    _repair_tool_calls(messages)


def _slim_images(messages: list[dict]) -> None:
    indexes = [
        index
        for index, message in enumerate(messages)
        if isinstance(message.get("content"), list)
        and any(isinstance(part, dict) and part.get("type") == "image_url" for part in message["content"])
    ]
    for index in indexes[:-1]:
        messages[index] = {
            "role": "user",
            "content": "An earlier screenshot was removed. Take a new screenshot if you still need to see the screen.",
        }


def _strip_old_reasoning(messages: list[dict]) -> None:
    assistants = [index for index, message in enumerate(messages) if message.get("role") == "assistant"]
    for index in assistants[:-1]:
        for key in ("reasoning", "reasoning_details", "reasoning_content"):
            messages[index].pop(key, None)


def _trim(messages: list[dict], keep: int) -> None:
    if len(messages) <= keep:
        return
    rest = messages[-(keep - 1) :]
    while rest and rest[0].get("role") == "tool":
        rest.pop(0)
    messages[:] = [messages[0], *rest]


async def _complete(llm: OpenRouter, messages: list[dict], cancel: threading.Event, shell: str):
    task = asyncio.create_task(llm.complete(messages, tool_list(shell)))
    while not task.done():
        if cancel.is_set():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            raise asyncio.CancelledError
        await asyncio.sleep(0.3)
    return await task


def _assistant_record(message: dict) -> dict:
    record = {"role": "assistant", "content": message.get("content")}
    if message.get("tool_calls"):
        record["tool_calls"] = message["tool_calls"]
    for key in ("reasoning", "reasoning_details", "reasoning_content"):
        if message.get(key):
            record[key] = message[key]
    return record


def _parse_call(call: dict) -> tuple[str, dict]:
    function = call.get("function") or {}
    name = function.get("name") or ""
    raw = function.get("arguments") or "{}"
    if isinstance(raw, str):
        try:
            args = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as exc:
            args = {"_error": f"Invalid JSON arguments: {exc}"}
    elif isinstance(raw, dict):
        args = raw
    else:
        args = {}
    return name, args


def _tool_message(call: dict, text: str) -> dict:
    return {"role": "tool", "tool_call_id": call.get("id") or "", "content": text}


def _image_message(result: ToolResult) -> dict:
    encoded = base64.b64encode(result.image or b"").decode("ascii")
    return {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": (
                    f"Screenshot attached, {result.width}x{result.height}. "
                    'Use coordinate_space "image" for the next click, drag, or scroll.'
                ),
            },
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
        ],
    }


def _text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts).strip()
    return str(content).strip()


def _cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... truncated"


def _add_cost(stats: RunStats, usage: dict) -> None:
    amount = _usage_cost(usage)
    if amount is None:
        return
    stats.cost += amount
    stats.cost_known = True


def _usage_cost(usage: dict) -> float | None:
    raw = usage.get("cost")
    if raw is None:
        raw = (usage.get("cost_details") or {}).get("upstream_inference_cost")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _user_turn(task: str, notes: str, image: bytes | None) -> dict:
    text = task
    if notes:
        text += "\n\nNotes you saved earlier:\n" + notes
    if not image:
        return {"role": "user", "content": text}
    encoded = base64.b64encode(image).decode("ascii")
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
        ],
    }


def _remember_cursor(memory: Memory | None, text: str) -> None:
    marker = "Opened Cursor in "
    if memory is None or marker not in text:
        return
    folder = text.split(marker, 1)[1]
    folder = folder.split(". ", 1)[0].rstrip(".").strip()
    if folder:
        memory.write("last_cursor_folder", folder)


def _budget_hit(stats: RunStats, limit: float) -> bool:
    if limit <= 0 or not stats.cost_known:
        return False
    return stats.cost >= limit * max(1, stats.budget_blocks)


async def _stop_for_budget(settings: Settings, stats: RunStats, events: AgentEvents) -> bool:
    if not _budget_hit(stats, settings.max_task_cost):
        return False
    allowed = await events.confirm(
        f"${stats.cost:.6f}",
        f"This task reached the ${settings.max_task_cost:.2f} cost limit. Allow another ${settings.max_task_cost:.2f}?",
    )
    if allowed:
        stats.budget_blocks += 1
        return False
    await events.final(
        "Stopped because the cost limit was reached. Send another message to continue.",
        _footer(stats, stats.steps),
    )
    return True


def _footer(stats: RunStats, steps: int) -> str:
    tokens = f"{steps} steps · {_compact(stats.prompt_tokens)} in · {_compact(stats.completion_tokens)} out"
    if stats.cost_known:
        return f"{tokens} · cost ${stats.cost:.6f}"
    return f"{tokens} · cost n/a"


def _compact(value: int) -> str:
    if value >= 1000:
        return f"{value / 1000:.1f}k"
    return str(value)


def _detail(name: str, args: dict) -> str:
    if name == "type_text":
        return str(args.get("text") or "")
    if name == "run_shell":
        return str(args.get("command") or "")
    if name == "press_keys":
        return str(args.get("keys") or "")
    if name == "launch":
        return " ".join(part for part in (str(args.get("target") or ""), str(args.get("args") or "")) if part)
    if name == "cursor_prompt":
        return one_line(str(args.get("text") or ""), 180)
    if name == "send_file":
        return str(args.get("path") or "")
    if name == "window":
        return " ".join(part for part in (str(args.get("action") or ""), str(args.get("title") or "")) if part)
    if name == "schedule":
        return one_line(str(args.get("instruction") or args.get("job_id") or ""), 180)
    if name == "memory":
        return str(args.get("key") or "")
    if name == "click":
        return f"{args.get('button', 'left')} ({args.get('x')}, {args.get('y')}) {args.get('coordinate_space', 'image')}"
    if name == "click_control":
        return " · ".join(
            part
            for part in (
                str(args.get("window") or ""),
                str(args.get("control_type") or ""),
                str(args.get("name") or ""),
            )
            if part
        )
    if name in {"focus_window", "ui_tree", "screenshot"}:
        return str(args.get("title") or args.get("window") or "")
    if name == "drag":
        return f"({args.get('x1')},{args.get('y1')}) → ({args.get('x2')},{args.get('y2')})"
    return ""


def _opt(args: dict, key: str) -> str | None:
    value = args.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _int(args: dict, key: str, default: int) -> int:
    try:
        return int(args.get(key, default))
    except (TypeError, ValueError):
        return default


async def _dispatch(
    desktop: Desktop,
    events: AgentEvents,
    name: str,
    args: dict,
    memory: Memory | None = None,
    schedule: Schedule | None = None,
    user_id: int = 0,
    chat_id: int = 0,
    inbox=None,
) -> ToolResult:
    if args.get("_error"):
        return ToolResult(str(args["_error"]))
    if name == "wait":
        seconds = max(0.2, min(_int(args, "seconds", 1), 8))
        remaining = seconds
        while remaining > 0:
            if events.cancel.is_set():
                return ToolResult("Cancelled.")
            tick = min(0.2, remaining)
            await asyncio.sleep(tick)
            remaining -= tick
        return ToolResult(f"Waited {seconds:.1f}s.")
    if name == "run_shell":
        command = str(args.get("command") or "").strip()
        if not command:
            return ToolResult("run_shell needs a command.")
        if len(command) > 8000:
            return ToolResult("Command is too long.")
        reason = danger_reason(command)
        if reason:
            allowed = await events.confirm(command, reason)
            if not allowed:
                return ToolResult("The user did not allow this command. Choose a safer action or ask them.")
        timeout = max(5, min(_int(args, "timeout_seconds", 60), 180))
        text = await asyncio.to_thread(
            desktop.run_shell,
            command,
            events.cancel,
            float(timeout),
            _opt(args, "cwd"),
        )
        return ToolResult(text)
    if name == "send_file":
        found, error = resolve_send_path(str(args.get("path") or ""), inbox)
        if error or not found:
            return ToolResult(error or "File not found.")
        return ToolResult(await events.send_file(found))
    if name == "cursor_prompt":
        text = await asyncio.to_thread(
            desktop.cursor_prompt,
            str(args.get("folder") or ""),
            str(args.get("text") or ""),
            _as_bool(args.get("send", True)),
        )
        _remember_cursor(memory, text)
        return ToolResult(text)
    if name == "clipboard_set":
        text = await asyncio.to_thread(desktop.clipboard_set, str(args.get("text") or ""))
        return ToolResult(text)
    if name == "window":
        text = await asyncio.to_thread(
            desktop.window_action,
            str(args.get("title") or ""),
            str(args.get("action") or ""),
            _int(args, "monitor", 1),
        )
        return ToolResult(text)
    if name == "memory":
        if memory is None:
            return ToolResult("Memory is not available.")
        action = str(args.get("action") or "read").strip().lower()
        if action == "write":
            return ToolResult(memory.write(str(args.get("key") or ""), str(args.get("value") or "")))
        return ToolResult(memory.read(str(args.get("key") or "")))
    if name == "schedule":
        if schedule is None:
            return ToolResult("Scheduling is not available.")
        action = str(args.get("action") or "list").strip().lower()
        if action == "add":
            return ToolResult(
                schedule.add(user_id, chat_id, str(args.get("instruction") or ""), _int(args, "delay_seconds", 60))
            )
        if action == "cancel":
            return ToolResult(schedule.cancel(str(args.get("job_id") or "")))
        return ToolResult(schedule.listing())
    if name == "screenshot":
        shot: Shot = await asyncio.to_thread(desktop.screenshot, _opt(args, "window"))
        return ToolResult(shot.text, image=shot.jpeg, width=shot.width, height=shot.height)

    call = {
        "list_windows": lambda: desktop.list_windows(),
        "foreground": lambda: desktop.foreground(),
        "focus_window": lambda: desktop.focus_window(str(args.get("title") or "")),
        "ui_tree": lambda: desktop.ui_tree(_opt(args, "window"), _int(args, "max_depth", 4), _int(args, "max_nodes", 160)),
        "click_control": lambda: desktop.click_control(
            str(args.get("name") or ""),
            _opt(args, "window"),
            _opt(args, "control_type"),
        ),
        "type_text": lambda: desktop.type_text(
            str(args.get("text") or ""),
            _opt(args, "window"),
            _opt(args, "control_name"),
            _as_bool(args.get("clear")),
        ),
        "press_keys": lambda: desktop.press_keys(str(args.get("keys") or "")),
        "launch": lambda: desktop.launch(str(args.get("target") or ""), str(args.get("args") or "")),
        "click": lambda: desktop.click(
            _int(args, "x", 0),
            _int(args, "y", 0),
            str(args.get("button") or "left"),
            str(args.get("coordinate_space") or "image"),
        ),
        "scroll": lambda: desktop.scroll(
            str(args.get("direction") or "down"),
            _int(args, "amount", 3),
            None if args.get("x") is None else _int(args, "x", 0),
            None if args.get("y") is None else _int(args, "y", 0),
            str(args.get("coordinate_space") or "screen"),
        ),
        "drag": lambda: desktop.drag(
            _int(args, "x1", 0),
            _int(args, "y1", 0),
            _int(args, "x2", 0),
            _int(args, "y2", 0),
            str(args.get("coordinate_space") or "image"),
        ),
        "clipboard_get": lambda: desktop.clipboard_get(),
    }.get(name)
    if call is None:
        return ToolResult(f"Unknown tool {name}.")
    text = await asyncio.to_thread(call)
    return ToolResult(str(text))


def _prop(kind: str, description: str, enum: list[str] | None = None) -> dict:
    schema: dict = {"type": kind, "description": description}
    if enum:
        schema["enum"] = enum
    return schema


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


def tool_list(shell: str) -> list[dict]:
    return [
    _tool("list_windows", "List titled top-level windows and which process owns them.", {}, []),
    _tool("foreground", "Read the foreground window, its process, and the focused control.", {}, []),
    _tool(
        "focus_window",
        "Bring a window to the front. title is a substring of the window title.",
        {"title": _prop("string", "Substring of the window title.")},
        ["title"],
    ),
    _tool(
        "ui_tree",
        "Read the accessibility tree of a window. Prefer this over a screenshot. Omit window to read the foreground window.",
        {
            "window": _prop("string", "Optional window title substring."),
            "max_depth": _prop("integer", "How deep to walk, 1 to 8. Default 4."),
            "max_nodes": _prop("integer", "How many controls to return, up to 220. Default 160."),
        },
        [],
    ),
    _tool(
        "click_control",
        "Move the mouse onto a named control and click it. Use the name from ui_tree.",
        {
            "name": _prop("string", "Visible name, or a unique substring of it."),
            "window": _prop("string", "Optional window title. Omit to use the foreground window."),
            "control_type": _prop("string", "Optional type such as Button, Edit, MenuItem, ListItem, Hyperlink, CheckBox, TabItem."),
        },
        ["name"],
    ),
    _tool(
        "type_text",
        "Paste text into a control. Works for Bengali and other Unicode. Click the target first if it is not focused.",
        {
            "text": _prop("string", "Text to paste."),
            "window": _prop("string", "Optional window title to focus first."),
            "control_name": _prop("string", "Optional control to click before pasting."),
            "clear": _prop("boolean", "Select all before pasting, replacing the current text."),
        },
        ["text"],
    ),
    _tool(
        "press_keys",
        "Press a key or chord. Examples: enter, esc, tab, ctrl+s, ctrl+shift+p, alt+tab, win+e, ctrl+a, delete. Not for sentences.",
        {"keys": _prop("string", "Key or chord. Separate a sequence with commas.")},
        ["keys"],
    ),
    _tool(
        "launch",
        "Open a program, file, folder, or URL. To open a folder in Cursor, target is cursor and args is the folder name or full path. A bare folder name is searched on the Desktop.",
        {
            "target": _prop("string", "Program name, path, folder, or URL. Use cursor to open Cursor."),
            "args": _prop("string", "For Cursor, the folder to open. Otherwise optional arguments."),
        },
        ["target"],
    ),
    _tool(
        "run_shell",
        f"Run a {shell} command and return its output. Use this for files and system queries, not for clicking windows.",
        {
            "command": _prop("string", f"{shell} command."),
            "cwd": _prop("string", "Optional working directory."),
            "timeout_seconds": _prop("integer", "Limit, 5 to 180. Default 60."),
        },
        ["command"],
    ),
    _tool(
        "screenshot",
        "Capture the desktop or one window and attach the image. Use only when the accessibility tree cannot do the job.",
        {"window": _prop("string", "Optional window title. Omit for the whole desktop.")},
        [],
    ),
    _tool(
        "click",
        "Click a pixel. After a screenshot, x and y are image pixels and coordinate_space is image.",
        {
            "x": _prop("integer", "X pixel."),
            "y": _prop("integer", "Y pixel."),
            "button": _prop("string", "left, right, middle, or double.", ["left", "right", "middle", "double"]),
            "coordinate_space": _prop("string", "image after a screenshot, otherwise screen.", ["image", "screen"]),
        },
        ["x", "y"],
    ),
    _tool(
        "scroll",
        "Scroll at the current mouse position, or at a point.",
        {
            "direction": _prop("string", "up or down.", ["up", "down"]),
            "amount": _prop("integer", "Notches, 1 to 12."),
            "x": _prop("integer", "Optional x."),
            "y": _prop("integer", "Optional y."),
            "coordinate_space": _prop("string", "image or screen.", ["image", "screen"]),
        },
        ["direction"],
    ),
    _tool(
        "drag",
        "Drag with the left button. Use image coordinates after a screenshot.",
        {
            "x1": _prop("integer", "Start x."),
            "y1": _prop("integer", "Start y."),
            "x2": _prop("integer", "End x."),
            "y2": _prop("integer", "End y."),
            "coordinate_space": _prop("string", "image or screen.", ["image", "screen"]),
        },
        ["x1", "y1", "x2", "y2"],
    ),
    _tool("clipboard_get", "Read text currently on the Windows clipboard.", {}, []),
    _tool(
        "clipboard_set",
        "Copy text onto the Windows clipboard.",
        {"text": _prop("string", "Text to copy.")},
        ["text"],
    ),
    _tool(
        "cursor_prompt",
        "Open a folder in Cursor, focus it, open the agent panel, paste text, and press Enter. Use this when Cursor's AI should do the work.",
        {
            "folder": _prop("string", "Folder name or full path. A bare name is searched on the Desktop."),
            "text": _prop("string", "Instruction to paste into Cursor's agent panel."),
            "send": _prop("boolean", "Press Enter after pasting. Default true."),
        },
        ["text"],
    ),
    _tool(
        "send_file",
        "Send a file from this PC to the Telegram chat. Do not use this for .env or key files.",
        {"path": _prop("string", "Full path or a file name on the Desktop, in Documents, Downloads, or the inbox.")},
        ["path"],
    ),
    _tool(
        "window",
        "Minimize, maximize, restore, or move a window onto a monitor.",
        {
            "title": _prop("string", "Substring of the window title."),
            "action": _prop("string", "minimize, maximize, restore, or move.", ["minimize", "maximize", "restore", "move"]),
            "monitor": _prop("integer", "For move, monitor number starting at 1. Default 1."),
        },
        ["title", "action"],
    ),
    _tool(
        "memory",
        "Read or write a short note that survives the next task. Empty value forgets the note.",
        {
            "action": _prop("string", "read or write.", ["read", "write"]),
            "key": _prop("string", "Note name, such as last_cursor_folder. Omit on read to list all."),
            "value": _prop("string", "Text to store when action is write."),
        },
        ["action"],
    ),
    _tool(
        "schedule",
        "Run an instruction later while OpenCtrl is open. Delay is 15 seconds to 24 hours.",
        {
            "action": _prop("string", "add, list, or cancel.", ["add", "list", "cancel"]),
            "instruction": _prop("string", "What to do when the timer fires."),
            "delay_seconds": _prop("integer", "How long to wait. Default 60."),
            "job_id": _prop("string", "Id to cancel."),
        },
        ["action"],
    ),
    _tool(
        "wait",
        "Pause briefly so a window can open. Prefer under 3 seconds.",
        {"seconds": _prop("integer", "Seconds, up to 8.")},
        ["seconds"],
    ),
    ]
