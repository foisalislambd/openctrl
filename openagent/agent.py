"""The desktop loop. The model sees tools, not a script of clicks written ahead of time."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
from dataclasses import dataclass, field

from openagent.config import Settings
from openagent.desktop import Desktop, Shot, run_powershell
from openagent.format_tg import humanize, one_line
from openagent.llm import LLMError, OpenRouter
from openagent.safety import danger_reason

log = logging.getLogger("openagent.agent")

SYSTEM = """You are OpenAgent. You operate the user's own Windows PC from Telegram. The user watches the screen and the chat.

Work in small steps.
- Prefer the accessibility tree: foreground, list_windows, focus_window, ui_tree, click_control, type_text, press_keys.
- Take a screenshot only when the tree has no usable control, the UI is custom-drawn, or you must see pixels. Do not screenshot every step.
- After a screenshot, the next message contains the image. Do not click, drag, or scroll in the same step as the screenshot. On the following step use coordinate_space "image". (0, 0) is the top-left of that image.
- ui_tree lines include screen coordinates like @x,y widthxheight. Those are screen pixels. Use coordinate_space "screen" only for those numbers.
- launch opens programs, files, folders, and URLs. To open a folder in Cursor, call launch with target "cursor" and args set to the folder name or full path. A bare name is searched on the Desktop. Do not click through the Cursor GUI to open a folder. run_powershell is for files, settings, and text output. Do not use PowerShell to click a GUI.
- type_text pastes Unicode, including Bengali, into the focused control. Click the edit box first when it is not already focused.
- press_keys is only for chords and single keys: ctrl+s, alt+tab, win+e, enter, ctrl+shift+p. Never put a sentence in press_keys.
- After an action, check the result with foreground or ui_tree before saying it worked. If a tool returns an error, change approach. Do not repeat the same failed call.
- When tool calls are present, put one short status sentence in the assistant content, in English. That sentence is shown in Telegram. No hidden plan, no markdown heading.
- When the task is finished or you are blocked, stop calling tools and write a clear summary in English: what changed, where things are, and what you need if you are blocked.
- Never invent passwords, codes, or confirmation prompts. If a secure desktop, UAC prompt, login, or lock screen is in the way, stop and ask the user.
- You only control this PC. Do not send the user's files or secrets anywhere except the Telegram chat they are already using.
"""


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


def fresh_history() -> list[dict]:
    return [{"role": "system", "content": SYSTEM}]


async def run_agent(
    settings: Settings,
    llm: OpenRouter,
    desktop: Desktop,
    messages: list[dict],
    task: str,
    events: AgentEvents,
) -> None:
    _repair_tool_calls(messages)
    messages.append({"role": "user", "content": task})
    stats = RunStats()
    try:
        for step in range(1, settings.max_steps + 1):
            if events.cancel.is_set():
                await events.stopped()
                return
            _pull_inbox(messages, events.inbox)
            _prepare(messages)
            try:
                message, usage = await _complete(llm, messages, events.cancel)
            except asyncio.CancelledError:
                await events.stopped()
                return
            except LLMError as exc:
                await events.fail(str(exc))
                return
            stats.prompt_tokens += int(usage.get("prompt_tokens") or 0)
            stats.completion_tokens += int(usage.get("completion_tokens") or 0)
            tool_calls = message.get("tool_calls") or []
            narration = one_line(_text(message.get("content")))
            messages.append(_assistant_record(message))
            if not tool_calls:
                await events.final(_text(message.get("content")) or "Done.", _footer(stats, step))
                return
            stats.steps = step
            images: list[ToolResult] = []
            for call in tool_calls:
                if events.cancel.is_set():
                    messages.append(_tool_message(call, "Cancelled by the user."))
                    continue
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
                    result = await _dispatch(desktop, events, name, args)
                except Exception as exc:
                    log.exception("Tool %s failed", name)
                    result = ToolResult(text=f"Tool error: {exc}")
                messages.append(_tool_message(call, _cap(result.text, 9000)))
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


def _pull_inbox(messages: list[dict], inbox: asyncio.Queue) -> None:
    notes: list[str] = []
    while True:
        try:
            notes.append(inbox.get_nowait())
        except asyncio.QueueEmpty:
            break
    if notes:
        messages.append(
            {
                "role": "user",
                "content": "New instruction while you are working:\n" + "\n".join(notes),
            }
        )


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


async def _complete(llm: OpenRouter, messages: list[dict], cancel: threading.Event):
    task = asyncio.create_task(llm.complete(messages, TOOLS))
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


def _footer(stats: RunStats, steps: int) -> str:
    return f"{steps} steps · {_compact(stats.prompt_tokens)} in · {_compact(stats.completion_tokens)} out"


def _compact(value: int) -> str:
    if value >= 1000:
        return f"{value / 1000:.1f}k"
    return str(value)


def _detail(name: str, args: dict) -> str:
    if name == "type_text":
        return str(args.get("text") or "")
    if name == "run_powershell":
        return str(args.get("command") or "")
    if name == "press_keys":
        return str(args.get("keys") or "")
    if name == "launch":
        return " ".join(part for part in (str(args.get("target") or ""), str(args.get("args") or "")) if part)
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


async def _dispatch(desktop: Desktop, events: AgentEvents, name: str, args: dict) -> ToolResult:
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
    if name == "run_powershell":
        command = str(args.get("command") or "").strip()
        if not command:
            return ToolResult("run_powershell needs a command.")
        if len(command) > 8000:
            return ToolResult("Command is too long.")
        reason = danger_reason(command)
        if reason:
            allowed = await events.confirm(command, reason)
            if not allowed:
                return ToolResult("The user did not allow this command. Choose a safer action or ask them.")
        timeout = max(5, min(_int(args, "timeout_seconds", 60), 180))
        text = await asyncio.to_thread(
            run_powershell,
            command,
            events.cancel,
            float(timeout),
            _opt(args, "cwd"),
        )
        return ToolResult(text)
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


TOOLS = [
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
        "run_powershell",
        "Run a PowerShell command and return its output. Use this for files and system queries, not for clicking windows.",
        {
            "command": _prop("string", "PowerShell command."),
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
        "wait",
        "Pause briefly so a window can open. Prefer under 3 seconds.",
        {"seconds": _prop("integer", "Seconds, up to 8.")},
        ["seconds"],
    ),
]
