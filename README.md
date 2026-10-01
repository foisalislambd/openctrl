# OpenAgent

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

- One live status message, with a Stop button
- A photo when a screenshot is needed
- A summary at the end
- A message sent while a task is running becomes the next instruction
- `/stop` cancels, `/reset` forgets the conversation, `/help` explains the commands

Disk format, shutdown, registry deletes, and recursive deletes of system folders wait for Allow. Everything else runs immediately.

## Limits

It stops and asks on a UAC prompt, a login, a captcha, or a custom-drawn UI with no names. It will not type a password on its own.
