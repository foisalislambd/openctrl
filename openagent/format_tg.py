"""Telegram HTML. The Bot API does not render arbitrary Markdown, so we convert a safe subset."""

from __future__ import annotations

import html
import re

_FENCE = re.compile(r"```[^\n`]*\n?(.*?)```", re.S)
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_CODE = re.compile(r"`([^`]+)`")
_BULLET = re.compile(r"^[-*] ")
_NUMBER = re.compile(r"^(\d+)\. (.*)$")


def escape(text: str) -> str:
    return html.escape(text or "", quote=False)


def markdown_to_html(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").strip()
    pieces: list[str] = []
    cursor = 0
    for match in _FENCE.finditer(text):
        pieces.append(_blocks(text[cursor : match.start()]))
        pieces.append(f"<pre>{escape(match.group(1).strip('\n'))}</pre>")
        cursor = match.end()
    pieces.append(_blocks(text[cursor:]))
    return "\n".join(part for part in pieces if part).strip()


def chunks(text: str, limit: int = 3900) -> list[str]:
    body = text or ""
    if len(body) <= limit:
        return [body] if body else ["…"]
    parts: list[str] = []
    current: list[str] = []
    size = 0
    for line in body.split("\n"):
        extra = len(line) + 1
        if current and size + extra > limit:
            parts.append("\n".join(current))
            current = []
            size = 0
        if len(line) > limit:
            if current:
                parts.append("\n".join(current))
                current = []
                size = 0
            for start in range(0, len(line), limit):
                parts.append(line[start : start + limit])
            continue
        current.append(line)
        size += extra
    if current:
        parts.append("\n".join(current))
    return parts


def one_line(text: str, limit: int = 280) -> str:
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1] + "…"


def render_welcome(user_id: int, allowed: bool) -> str:
    if not allowed:
        return (
            "<b>OpenAgent</b>\n"
            "This chat can control your Windows PC. You are not allowed yet.\n\n"
            "<b>Your Telegram id</b>\n"
            f"<code>{user_id}</code>\n\n"
            "Put this number in <code>TELEGRAM_ALLOWED_USER_IDS</code> in <code>.env</code>, "
            "then stop the bot and start it again."
        )
    return (
        "<b>OpenAgent</b>\n"
        "While the PC is unlocked, send a task and the agent will do it. "
        "Each step shows up in this chat.\n\n"
        "<b>Examples</b>\n"
        "<blockquote>Open Notepad and type: meeting tomorrow at 4</blockquote>\n"
        "<blockquote>Open Cursor in the openagent folder on the Desktop and send this text in the chat</blockquote>\n\n"
        "<i>/help</i>  ·  <i>/stop</i>  ·  <i>/reset</i>  ·  <i>/schedule</i>\n"
        f"<code>id {user_id}</code>"
    )


def render_help() -> str:
    return (
        "<b>What OpenAgent can do</b>\n"
        "Ordinary Windows work: open apps, focus windows, click buttons, type, "
        "files, settings, the browser, Cursor. It reads the accessibility tree first, "
        "so it does not screenshot every step. It takes a picture only when a control has no name.\n\n"
        "<b>Commands</b>\n"
        "• <code>/stop</code> — stop the current task\n"
        "• <code>/reset</code> — forget the conversation\n"
        "• <code>/schedule</code> — list tasks waiting to run\n"
        "• <code>/help</code> — this message\n\n"
        "<b>Also</b>\n"
        "Send a file, a photo, or a voice note. Files are saved in the inbox and can be sent back. "
        "A voice note is transcribed, then run as a task.\n"
        "Say when something should happen later, up to 24 hours, while OpenAgent is open.\n"
        "A task stops to ask before spending more than the cost limit.\n\n"
        "<b>While it is working</b>\n"
        "A new message is added as the next instruction.\n"
        "Disk format, shutdown, and registry deletes ask for Allow first.\n\n"
        "<blockquote>If the PC is locked, the agent stops and asks you to unlock it. The screen stays awake during a task.</blockquote>"
    )


def render_started(task: str) -> str:
    return (
        "<b>▶ Started</b>\n"
        f"<blockquote>{escape(one_line(task, 700))}</blockquote>\n"
        "<i>Working on the PC. Press Stop to cancel.</i>"
    )


def render_progress(
    step: int,
    max_steps: int,
    narration: str,
    action: str,
    detail: str,
    result: str,
) -> str:
    return _step_card(step, max_steps, narration, action, detail, result, detail_limit=700, result_limit=500)


def render_caption(
    step: int,
    max_steps: int,
    narration: str,
    action: str,
    detail: str,
    result: str,
    width: int,
    height: int,
) -> str:
    card = _step_card(step, max_steps, narration, action, detail, result, detail_limit=180, result_limit=280)
    caption = f"{card}\n<i>{width}×{height}</i>"
    if len(caption) <= 1000:
        return caption
    short = _step_card(step, max_steps, narration, action, "", "", detail_limit=0, result_limit=0)
    return f"{short}\n<i>{width}×{height}</i>"


def _step_card(
    step: int,
    max_steps: int,
    narration: str,
    action: str,
    detail: str,
    result: str,
    detail_limit: int,
    result_limit: int,
) -> str:
    lines = [
        f"<b>Step {step}/{max_steps}</b>  ·  <code>{escape(action or 'working')}</code>",
        f"<blockquote>{escape(narration or action or 'Working')}</blockquote>",
    ]
    if detail and detail_limit:
        lines.append(f"<pre>{escape(_clip(detail, detail_limit))}</pre>")
    if result and result_limit:
        lines.append(f"<pre>{escape(_clip(result.strip(), result_limit))}</pre>")
    return "\n".join(lines)


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def render_final(text: str, footer: str) -> str:
    body = markdown_to_html(text) or escape("The summary came back empty.")
    foot = f"\n\n<i>{escape(footer)}</i>" if footer else ""
    return f"<b>✓ Done</b>\n\n{body}{foot}"


def render_stopped(footer: str = "") -> str:
    foot = f"\n<i>{escape(footer)}</i>" if footer else ""
    return f"<b>■ Stopped</b>\n<i>Send another task whenever you want.</i>{foot}"


def render_error(text: str, footer: str = "") -> str:
    foot = f"\n<i>{escape(footer)}</i>" if footer else ""
    return f"<b>Blocked</b>\n<pre>{escape(one_line(text, 1200))}</pre>{foot}"


def render_queued() -> str:
    return "<i>Added to the task that is already running.</i>"


def render_confirm(command: str, reason: str) -> str:
    return (
        "<b>Confirm</b>\n"
        f"<blockquote>{escape(reason)}</blockquote>\n"
        f"<pre>{escape(one_line(command, 900))}</pre>\n"
        "<i>The command will not run unless you press Allow.</i>"
    )


def humanize(name: str, args: dict) -> str:
    titles = {
        "list_windows": "Looking at open windows",
        "foreground": "Reading the front window",
        "focus_window": f"Focusing {args.get('title', '')}",
        "ui_tree": "Reading the app's controls",
        "click_control": f"Clicking {args.get('name', '')}",
        "type_text": "Typing",
        "press_keys": f"Pressing {args.get('keys', '')}",
        "launch": f"Opening {args.get('target', '')}",
        "run_powershell": "Running PowerShell",
        "screenshot": "Looking at the screen",
        "click": "Clicking",
        "scroll": "Scrolling",
        "drag": "Dragging",
        "clipboard_get": "Reading the clipboard",
        "clipboard_set": "Copying to the clipboard",
        "cursor_prompt": "Sending a prompt to Cursor",
        "send_file": "Sending a file",
        "window": f"{str(args.get('action') or 'Moving').capitalize()} {args.get('title', '')}".strip(),
        "memory": "Saving a note" if args.get("action") == "write" else "Reading notes",
        "schedule": "Scheduling a task",
        "wait": "Waiting",
    }
    return titles.get(name, name)


def _blocks(text: str) -> str:
    if not text.strip():
        return ""
    rendered: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("### "):
            rendered.append(f"<b>{_spans(stripped[4:])}</b>")
        elif stripped.startswith("## "):
            rendered.append(f"<b>{_spans(stripped[3:])}</b>")
        elif stripped.startswith("# "):
            rendered.append(f"<b>{_spans(stripped[2:])}</b>")
        elif stripped.startswith("> "):
            rendered.append(f"<blockquote>{_spans(stripped[2:])}</blockquote>")
        elif _BULLET.match(stripped):
            rendered.append("• " + _spans(stripped[2:]))
        else:
            numbered = _NUMBER.match(stripped)
            if numbered:
                rendered.append(f"{numbered.group(1)}. {_spans(numbered.group(2))}")
            else:
                rendered.append(_spans(line))
    return "\n".join(rendered).strip()


def _spans(text: str) -> str:
    parts = _CODE.split(text)
    out: list[str] = []
    for index, part in enumerate(parts):
        if index % 2 == 1:
            out.append(f"<code>{escape(part)}</code>")
        else:
            out.append(_links_and_bold(part))
    return "".join(out)


def _links_and_bold(text: str) -> str:
    out: list[str] = []
    cursor = 0
    for match in _LINK.finditer(text):
        out.append(_bold(text[cursor : match.start()]))
        href = html.escape(match.group(2), quote=True)
        out.append(f'<a href="{href}">{escape(match.group(1))}</a>')
        cursor = match.end()
    out.append(_bold(text[cursor:]))
    return "".join(out)


def _bold(text: str) -> str:
    out: list[str] = []
    cursor = 0
    for match in _BOLD.finditer(text):
        out.append(escape(text[cursor : match.start()]))
        out.append(f"<b>{escape(match.group(1))}</b>")
        cursor = match.end()
    out.append(escape(text[cursor:]))
    return "".join(out)
