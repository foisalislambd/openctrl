# OpenCtrl

OpenCtrl lets you run your own computer from a Telegram chat. You describe a task in normal language. The program on that computer does the work, and each step comes back in the same chat.

The same agent runs on Windows, macOS, and Linux. Each system has its own app window and its own way of clicking the desktop. The chat, the model, the tools, and the safety checks are shared. You set the keys in that window. The agent starts with the app.

It is for the computer you are already logged into. It is not a remote-admin product, and it is not a cloud agent that holds your files. The bot runs in your desktop session. The language model only sees the tool results needed for the current task.

## Why this exists

A lot of desktop work is still “open this, click that, type this.” Doing it from a phone usually means a remote-desktop app, which is a live video of the whole screen. OpenCtrl is the other shape: you send a sentence, and a small set of tools does the clicks.

That matters for three reasons.

- **You stay in the chat.** The task, each step, screenshots, and the final summary are messages. You can stop it, add a new instruction, or ask it to send a file back.
- **It uses names before pixels.** Where the desktop exposes a button's name, OpenCtrl reads that accessibility tree first. A screenshot is a fallback, not the default. On Linux, if the session has no accessibility tree, it says so and uses the screenshot.
- **The dangerous parts wait.** Formatting a disk, shutting down, and recursive deletes of a system or home folder ask for Allow. `.env`, the settings database, and key files are not sent back to Telegram. Anyone whose id is not in your allow list cannot start a task.

## How a task runs

```text
You (Telegram)
    │  "Open Notepad and type: meeting tomorrow at 4"
    ▼
OpenCtrl on your computer
    │  sends the task, plus short notes from earlier, to OpenRouter
    ▼
The model picks one tool
    │  list windows, read the UI tree, click a named control, type, …
    ▼
The computer
    │  the tool result goes back to the model
    ▼
Telegram
    each step is a new message; a summary and the cost close the task
```

The model does not receive a script of clicks written ahead of time. It works in small steps, looks at the result, and chooses the next tool. One task stops after `MAX_STEPS` (default 30), or earlier if you press Stop, the desktop locks, or the cost limit is reached.

While a task is running, the screen is kept awake. If the desktop is locked, OpenCtrl stops instead of clicking a screen it cannot see. A message you send during a task is added as the next instruction. It does not start a second task on top of the first one.

## What you can ask for

Talk to it the way you would talk to someone sitting at the computer.

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

A shell command that would format a disk, shut down or restart, or recursively delete a system or home folder waits for an Allow button in Telegram. On Windows that also covers registry deletes, diskpart, and boot edits. Ordinary file and settings commands run immediately.

Only private chats are accepted. Group chats are ignored. If no Telegram id is saved yet, `/start` still shows your id, and no task runs until you add it in the window.

## Requirements

- Windows 10 or 11, macOS, or a Linux desktop, in the session you want to control. The screen has to be unlocked.
- Python 3.12
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- An [OpenRouter](https://openrouter.ai/keys) API key

Linux clicks need an X11 session with `xdotool`, `wmctrl`, `scrot` or ImageMagick, and `xclip`. A Wayland session can take a screenshot with `grim`, and it will say when clicks are blocked. macOS needs Accessibility permission for the terminal that starts OpenCtrl.

The default model is `openai/gpt-6-luna-pro`. Voice notes use `openai/whisper-large-v3`. Both can be changed in the OpenCtrl window.

## Set it up

1. Clone this repository.
2. In Telegram, send `/newbot` to [@BotFather](https://t.me/BotFather) and keep the token.
3. Create an API key at [OpenRouter](https://openrouter.ai/keys).
4. While you are logged in on the computer you want to control, start the matching app.
   - Windows: double-click `run.bat` in this folder. It starts `apps/windows`. Do not run it as a Windows service.
   - macOS or Linux: `sh apps/macos/run.sh` or `sh apps/linux/run.sh`. That creates `.venv`, installs dependencies, and opens the window.
5. Paste the bot token and the OpenRouter key into the window. Click **Save and apply**. The agent starts on its own.
6. Send `/start` to your bot. It replies with your Telegram id.
7. Paste that id into **Allowed Telegram ids**. Several people can be listed, separated by commas. Only add people who should be able to operate this computer. Click **Save and apply** again.
8. Send a task in normal language.

The keys are stored in `data/openctrl.db` next to the app you started. They are not read from the environment. If a `.env` file is already there, the first launch copies it into that database and does not read it again. You can delete the `.env` after the window shows the keys.

A second copy in the same session exits immediately.

**Start OpenCtrl when I log in** is on by default. On Windows that is a Startup shortcut named `OpenCtrl.lnk`. On macOS it is a login item. On Linux it is an autostart entry. It is still a normal desktop program. An older Windows shortcut named `OpenAgent.lnk` is removed at that point. Turning the checkbox off removes that login item. **Start the agent when this app opens** is also on by default, so logging in opens the window and the agent starts with it.

## Settings

The window writes these into `data/openctrl.db`. Never commit that file, and do not send it back through Telegram.

| Field | Default | What it does |
| --- | --- | --- |
| Telegram bot token | empty | Token from BotFather. Required. |
| Allowed Telegram ids | empty | Telegram user ids allowed to run tasks. |
| OpenRouter API key | empty | OpenRouter key. Required. |
| Model | `openai/gpt-6-luna-pro` | Model that chooses the tools. |
| Provider sort | `exacto` | OpenRouter routing. Exacto is more reliable for tool calls. Leave empty for OpenRouter’s default route. |
| Voice model | `openai/whisper-large-v3` | Model used for voice notes. |
| Max steps | `30` | Most tool steps in one task. Clamped between 5 and 80. |
| Max reply tokens | `12000` | Token cap on each model reply. Clamped between 1000 and 32000. |
| Cost limit ($) | `0.50` | The task stops and asks before spending more than this. `0` turns the limit off. |
| Start the agent when this app opens | on | The agent starts as soon as the window opens. |
| Start OpenCtrl when I log in | on | Create the login shortcut. |

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
| `logs/openctrl.log` | Runtime log, inside the app folder you started. The window shows the latest lines. |
| `inbox/` | Files, photos, and videos received from Telegram. |
| `data/openctrl.db` | Bot token, API key, and the other settings. |
| `data/memory.json` | Short notes kept between tasks. |
| `data/schedules.json` | Timers that have not fired yet. |
| `.venv/` | Local Python environment created by `run.bat` or `run.sh`. |

These paths are gitignored, along with `.env`.

## Tools the model can call

You do not call these yourself. They are how the model touches the computer. Knowing the list makes the limits easier to understand.

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
| `run_shell` | Run a command and return its text. PowerShell on Windows, zsh on macOS, bash on Linux. Not for clicking the GUI. |
| `screenshot` | Capture the desktop or one window. |
| `click`, `scroll`, `drag` | Pixel actions. After a screenshot, coordinates are image pixels. |
| `clipboard_get`, `clipboard_set` | Read or write the clipboard. |
| `cursor_prompt` | Open a folder in Cursor, focus the agent panel, paste an instruction, and press Enter. |
| `send_file` | Post one file into the Telegram chat. Refuses `.env`, `openctrl.db`, key, and password files. |
| `window` | Minimize, maximize, restore, or move a window to a monitor. |
| `memory` | Read or write a short note. |
| `schedule` | Add, list, or cancel a delayed instruction. |
| `wait` | Pause up to 8 seconds so a window can open. |

## Repository

The chat, model, memory, timers, settings database, and safety checks live in `packages/core`. The setup window lives there too. Each operating system has an app that supplies the desktop: windows, clicks, typing, screenshots, and login.

```text
run.bat                         starts the Windows app
packages/core/openctrl/         shared agent, Telegram bot, model, safety
apps/windows/                   Windows desktop (UI Automation, PowerShell)
  openctrl_windows/             desktop, hotkeys, login shortcut
  main.py
  run.bat
apps/macos/                     macOS desktop (System Events, zsh)
  openctrl_macos/
  main.py
  run.sh
apps/linux/                     Linux desktop (xdotool, wmctrl, bash)
  openctrl_linux/
  main.py
  run.sh
```

Logs, inbox, and notes are created inside the app folder you start.

## Releases

The version is the `VERSION` file at the repository root, written as `major.minor.patch`. A push to `main` compares that number with the tags already published on GitHub.

- If `VERSION` is greater than the latest release, Actions builds the Windows, macOS, and Linux apps and publishes tag `vX.Y.Z` with the three zip files. The changelog section for that version becomes the release notes.
- If `VERSION` is equal to or lower than the latest release, the workflow stops and does not publish anything.
- The first push publishes a release when no release exists yet.

To ship the next one, raise `VERSION`, add a matching `## x.y.z` section to [CHANGELOG.md](CHANGELOG.md), and push `main`.

The zip from a release is the built app. Double-click `OpenCtrl.exe` on Windows, `OpenCtrl.app` on macOS, or the `OpenCtrl` program on Linux. A built app keeps its database in the user data folder (`%APPDATA%\OpenCtrl` on Windows). Running from this repository with `run.bat` or `run.sh` still keeps `data/openctrl.db` in the app folder.

## Develop

From the repository root, after a virtual environment exists:

```bat
set PYTHONPATH=packages\core;apps\windows
.venv\Scripts\python.exe -m unittest discover -s packages\core\tests
.venv\Scripts\python.exe -m unittest discover -s apps\windows\tests
```

The tests cover formatting, the safety rules, scheduling, memory, file paths, and hotkeys. They do not click a real desktop.

Changes that affect the chat or the desktop should be tried on a machine you are willing to let the bot control, with your own Telegram id in the allow list.

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to send a change, [SECURITY.md](SECURITY.md) for how to report a vulnerability, [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for how to work together, and [CHANGELOG.md](CHANGELOG.md) for what shipped.

## License

MIT. See [LICENSE](LICENSE).
