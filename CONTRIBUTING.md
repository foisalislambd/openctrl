# Contributing

OpenCtrl is a Windows desktop program that can click, type, and run PowerShell on the machine where it is running. Changes should stay easy to review and hard to misuse.

## Before you start

- Use your own PC, your own bot token, and your own OpenRouter key.
- Do not put `.env`, tokens, or chat logs in a commit, an issue, or a pull request.
- Windows and Python 3.12 are the supported setup. From the repository root, `run.bat` starts `apps/windows`, creates `.venv`, and installs `requirements.txt`. macOS and Linux folders are reserved and have no app yet.

## Checks

From the repository root, with `packages/core` and `apps/windows` on `PYTHONPATH`:

```bat
set PYTHONPATH=packages\core;apps\windows
.venv\Scripts\python.exe -m unittest discover -s packages\core\tests
.venv\Scripts\python.exe -m unittest discover -s apps\windows\tests
```

Add or extend a test when you change safety rules, scheduling, memory, file sending, hotkeys, or chat formatting. Desktop clicks are not covered by these tests, so describe how you tried a UI change on a real session.

## What a good change looks like

- Keep the accessibility tree as the first choice. A new click path that only uses pixels needs a reason.
- Dangerous shell commands belong in `packages/core/openctrl/safety.py`, with a test. Ordinary work should keep running without an Allow prompt.
- Secrets stay blocked in `packages/core/openctrl/files.py`. Do not add a way to send `.env`, `openctrl.db`, or key files to Telegram.
- User-facing chat text is short and in English, matching the messages already in `packages/core/openctrl/format_tg.py`.
- Leave unrelated files alone. Do not reformat the whole package in a feature change.

## Pull requests

- One change per pull request.
- Say what a person can do after the change that they could not do before.
- Say how you tested it.
- If you are not sure the behavior is wanted, open an issue first.
