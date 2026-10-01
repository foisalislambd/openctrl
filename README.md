# OpenCtrl

OpenCtrl lets you run your own Windows PC from a Telegram chat. You describe a task in normal language. The program on that PC does the work, and each step comes back in the same chat.

It is for the computer you are already logged into. It is not a remote-admin product, and it is not a cloud agent that holds your files. The bot runs in your desktop session. The language model only sees the tool results needed for the current task.

## Why this exists

A lot of desktop work is still “open this, click that, type this.” Doing it from a phone usually means a remote-desktop app, which is a live video of the whole screen. OpenCtrl is the other shape: you send a sentence, and a small set of tools does the clicks.

That matters for three reasons.

- **You stay in the chat.** The task, each step, screenshots, and the final summary are messages. You can stop it, add a new instruction, or ask it to send a file back.
- **It uses names before pixels.** Windows already knows that a control is a button called Save. OpenCtrl reads that accessibility tree first. A screenshot is a fallback, not the default. Named clicks survive theme changes and window moves better than guessing at pixels.
- **The dangerous parts wait.** Formatting a disk, shutting down, deleting registry keys, and recursive deletes of system folders ask for Allow. `.env` and key files are not sent back to Telegram. Anyone whose id is not in your allow list cannot start a task.

## How a task runs

```text
You (Telegram)
    │  "Open Notepad and type: meeting tomorrow at 4"
    ▼
OpenCtrl on your PC
    │  sends the task, plus short notes from earlier, to OpenRouter
    ▼
The model picks one tool
    │  list windows, read the UI tree, click a named control, type, …
    ▼
Windows
    │  the tool result goes back to the model
    ▼
Telegram
    each step is a new message; a summary and the cost close the task
```

The model does not receive a script of clicks written ahead of time. It works in small steps, looks at the result, and chooses the next tool. One task stops after `MAX_STEPS` (default 30), or earlier if you press Stop, the desktop locks, or the cost limit is reached.

While a task is running, the screen is kept awake. If the desktop is locked, OpenCtrl stops instead of clicking a screen it cannot see. A message you send during a task is added as the next instruction. It does not start a second task on top of the first one.

## What you can ask for

Talk to it the way you would talk to someone sitting at the PC.

- Open Notepad and type a sentence.
- Open a folder in Cursor and paste an instruction into Cursor’s agent panel.
- Copy text to the clipboard, or read what is already there.
- Move, resize, minimize, or maximize a window, including onto another monitor.
- Send a file, a photo, or a voice note. Files are saved in `inbox`. A voice note is transcribed, then run as a task.
- Ask it to send a file back. It looks on the Desktop, in Documents, Downloads, and `inbox`.
- “Do this in 10 minutes.” Timers run from 15 seconds up to 24 hours, as long as OpenCtrl itself is open.
- Remember a short note, such as the last folder you were using. Notes live in `data/memory.json` and are included with the next task. `/reset` forgets the conversation, not these notes.

Typing uses paste, so Bengali and other Unicode text work. Key chords (`Ctrl+S`, `Alt+Tab`, `Win+E`) are separate from typed sentences.

## What it will not do on its own

It stops and tells you when it hits something it should not guess through:

- A UAC prompt, a login, a captcha, or the lock screen
- A custom-drawn window whose controls have no names
- Typing a password

PowerShell that would format a disk, shut down or restart, edit boot configuration, delete registry keys, wipe free space, or recursively delete a system folder or a drive root waits for an Allow button in Telegram. Ordinary file and settings commands run immediately.

Only private chats are accepted. Group chats are ignored. If `TELEGRAM_ALLOWED_USER_IDS` is empty, `/start` still shows your id, and no task runs until you add it.

## Requirements

- Windows 10 or 11, in the desktop session you want to control. The screen has to be unlocked.
- Python 3.12
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- An [OpenRouter](https://openrouter.ai/keys) API key

The default model is `openai/gpt-6-luna-pro`. Voice notes use `openai/whisper-large-v3`. Both can be changed in `.env`.

## Set it up

1. Clone this repository and open a terminal in the project folder.
2. In Telegram, send `/newbot` to [@BotFather](https://t.me/BotFather) and keep the token.
3. Create an API key at [OpenRouter](https://openrouter.ai/keys).
4. Copy `.env.example` to `.env` and paste both keys.
5. On the PC you want to control, while you are logged in, double-click `run.bat`.

   `run.bat` creates `.venv` if it is missing, installs `requirements.txt`, and starts `main.py`. Do not run it as a Windows service. A service has no desktop to click.

6. Send `/start` to your bot. It replies with your Telegram id.
7. Put that id in `TELEGRAM_ALLOWED_USER_IDS` in `.env`. Several people can be listed, separated by commas. Only add people who should be able to operate this PC.
8. Stop the bot (close the window, or Ctrl+C) and run `run.bat` again.
9. Send a task in normal language.

A second copy in the same Windows session exits immediately. The log line is `OpenCtrl is already running in this Windows session.`

With `START_WITH_WINDOWS=1` (the default), the first successful start creates a Startup shortcut named `OpenCtrl.lnk`. It opens when you log on. It is still a normal desktop program. An older shortcut named `OpenAgent.lnk` is removed at that point.

## Settings

All of these live in `.env`. Never commit that file.

| Name | Default | What it does |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | empty | Token from BotFather. Required. |
| `TELEGRAM_ALLOWED_USER_IDS` | empty | Comma-separated Telegram user ids allowed to run tasks. |
| `OPENROUTER_API_KEY` | empty | OpenRouter key. Required. |
| `OPENROUTER_MODEL` | `openai/gpt-6-luna-pro` | Model that chooses the tools. |
| `OPENROUTER_PROVIDER_SORT` | `exacto` | OpenRouter routing. Exacto is more reliable for tool calls. Leave empty for OpenRouter’s default route. |
| `OPENROUTER_TRANSCRIBE_MODEL` | `openai/whisper-large-v3` | Model used for voice notes. |
| `MAX_STEPS` | `30` | Most tool steps in one task. Clamped between 5 and 80. |
| `MAX_OUTPUT_TOKENS` | `12000` | Token cap on each model reply. Clamped between 1000 and 32000. |
| `MAX_TASK_COST` | `0.50` | Dollars. The task stops and asks before spending more than this. `0` turns the limit off. |
| `START_WITH_WINDOWS` | `1` | Create the login shortcut. `0`, `false`, `no`, or `off` skips it. |

## Commands

| Command | What it does |
| --- | --- |
| `/start` | Shows your Telegram id and a short welcome. |
| `/help` | What the bot can do, in the chat. |
| `/stop` | Cancels the current task. The latest step also has a Stop button. |
| `/reset` | Forgets the conversation. Stop the current task first. |
| `/schedule` | Lists timers that have not fired yet. |

Anything else that starts with `/` is answered with “Unknown command.”

## What you see in the chat

- The task stays at the top. Each step is a new message under it, in order.
- A screenshot, when one is taken, is posted in that same sequence. The step is written on the picture.
- The last message is a summary, plus the OpenRouter cost for that task when the provider reported one.
- A message sent while a task is running becomes the next instruction, and the chat says it was queued.
- An Allow / Cancel prompt appears only for the dangerous commands listed above.

## Folders the program creates

| Path | What is in it |
| --- | --- |
| `logs/openctrl.log` | Runtime log. |
| `inbox/` | Files, photos, and videos received from Telegram. |
| `data/memory.json` | Short notes kept between tasks. |
| `data/schedules.json` | Timers that have not fired yet. |
| `.venv/` | Local Python environment created by `run.bat`. |

These paths are gitignored, along with `.env`.

## Tools the model can call

You do not call these yourself. They are how the model touches the PC. Knowing the list makes the limits easier to understand.

| Tool | What it does |
| --- | --- |
| `list_windows` | Titled windows and which process owns them. |
| `foreground` | The front window and the focused control. |
| `focus_window` | Bring a window forward by a piece of its title. |
| `ui_tree` | The accessibility tree: names, types, and screen coordinates. |
| `click_control` | Click a control by its name. |
| `type_text` | Paste text, including Unicode. Can clear the field first. |
| `press_keys` | One key or a chord. Not a sentence. |
| `launch` | Open a program, file, folder, or URL. `cursor` plus a folder opens that folder in Cursor. |
| `run_powershell` | Run a command and return its text. Not for clicking the GUI. |
| `screenshot` | Capture the desktop or one window. |
| `click`, `scroll`, `drag` | Pixel actions. After a screenshot, coordinates are image pixels. |
| `clipboard_get`, `clipboard_set` | Read or write the Windows clipboard. |
| `cursor_prompt` | Open a folder in Cursor, focus the agent panel, paste an instruction, and press Enter. |
| `send_file` | Post one file into the Telegram chat. Refuses `.env`, key, and password files. |
| `window` | Minimize, maximize, restore, or move a window to a monitor. |
| `memory` | Read or write a short note. |
| `schedule` | Add, list, or cancel a delayed instruction. |
| `wait` | Pause up to 8 seconds so a window can open. |

## Project layout

```text
main.py                 starts logging, the single-instance check, and the bot
run.bat                 creates the venv, installs dependencies, runs main.py
requirements.txt        Python packages
.env.example            settings template
openctrl/               the package
  agent.py              the step loop and the tool list
  bot.py                Telegram commands, files, voice notes, confirmations
  desktop.py            windows, accessibility tree, mouse, keyboard, screenshots
  llm.py                OpenRouter chat and transcription
  safety.py             commands that must wait for Allow
  files.py              inbox uploads and the secret-file block
  schedule.py           delayed tasks
  memory.py             notes kept between tasks
  startup.py            the login shortcut
  format_tg.py          chat messages
  hotkeys.py            key chords
  awake.py              keep the screen awake during a task
  config.py             reads .env
tests/test_core.py      unit tests that do not need a live desktop
```

## Develop

From the project folder, with the virtual environment already created by `run.bat`:

```bat
.venv\Scripts\python.exe -m unittest tests.test_core
```

The tests cover formatting, the safety rules, scheduling, memory, file paths, and hotkeys. They do not click a real desktop.

Changes that affect the chat or the desktop should be tried on a machine you are willing to let the bot control, with your own Telegram id in the allow list.

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to send a change, [SECURITY.md](SECURITY.md) for how to report a vulnerability, [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for how to work together, and [CHANGELOG.md](CHANGELOG.md) for what shipped.

## License

MIT. See [LICENSE](LICENSE).
