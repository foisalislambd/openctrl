# OpenCtrl

An agent that controls your own Windows PC from Telegram. You send a task, it does the work, and each step is posted back in the chat.

It is not limited to Cursor. Notepad, Explorer, the browser, Settings, Cursor — anywhere a control has a name, it uses the accessibility tree. It takes a screenshot only when the tree has no usable control.

The model is OpenRouter's `openai/gpt-6-luna-pro`. Change `OPENROUTER_MODEL` in `.env` if you want a different one.

## Start

1. In Telegram, tell [@BotFather](https://t.me/BotFather) `/newbot` and keep the token.
2. Create an API key at [OpenRouter](https://openrouter.ai/keys).
3. Copy `.env.example` to `.env` and fill in both keys.
4. On this PC, in the logged-in desktop session, run `run.bat`. Do not run it as a service. The desktop has to be visible.
5. Send `/start` to the bot. Put the id it shows into `TELEGRAM_ALLOWED_USER_IDS` in `.env`.
6. Stop the bot and run `run.bat` again. Then describe the task in normal language.

The PC must stay unlocked. On the lock screen or while asleep, the agent cannot see anything.

## In the chat

- The task stays at the top. Each step is a new message under it, in order, with Stop on the latest one
- A screenshot is posted in that same sequence, with the step written on the picture
- A summary at the end, including the OpenRouter cost for that task
- A message sent while a task is running becomes the next instruction
- `/stop` cancels, `/reset` forgets the conversation, `/schedule` lists timers, `/help` explains the commands

Send a file, a photo, or a voice note. Files land in `inbox`. A voice note is transcribed and then run. Ask the agent to send a file back and it posts it in the chat.

You can tell it to open a folder in Cursor and paste an instruction into Cursor's agent panel. It can copy text to the clipboard, move or resize windows across monitors, and remember short notes such as the last folder.

"Do this in 10 minutes" waits and then runs, as long as OpenCtrl is open. The screen stays awake while a task is running. If the desktop is locked, it stops instead of clicking blindly. A task also stops to ask before it spends more than `MAX_TASK_COST`.

With `START_WITH_WINDOWS=1`, a Startup shortcut opens OpenCtrl when you log on. It still runs in the desktop session, not as a service.

Disk format, shutdown, registry deletes, and recursive deletes of system folders wait for Allow. Everything else runs immediately. `.env` and key files are not sent back to Telegram.

## Limits

It stops and asks on a UAC prompt, a login, a captcha, or a custom-drawn UI with no names. It will not type a password on its own.
