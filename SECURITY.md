# Security

OpenCtrl can operate the Windows desktop it is running on. Treat the bot token, the OpenRouter key, and the allow list as access to that PC.

## Use it safely

- Keep `data/openctrl.db` on the PC only. It holds the bot token and API key, and it is gitignored. An old `.env` is copied into that database once. Do not paste either file into chat, issues, or screenshots.
- Put only your own Telegram user id, or people you trust with this computer, in `TELEGRAM_ALLOWED_USER_IDS`.
- Leave the bot in a private chat. The program ignores groups, but a leaked token still lets someone else host a copy.
- Do not run OpenCtrl on a PC you do not want the allow-listed users to control.
- The cost cap and the Allow prompts are limits, not a sandbox. A confirmed command runs with the same Windows user that started `run.bat`.

The program refuses to send `.env`, `openctrl.db`, files whose names end in `.pem` or `.key`, and a short list of credential filenames back to Telegram. That block is not a full secret scanner.

## Reporting a vulnerability

Please do not open a public issue for a security bug.

Email the details to the address on the latest commit in this repository. Include what is affected, how to reproduce it, and what an attacker could do. Give the project a chance to fix it before you publish the details.

Useful reports include:

- A way for someone outside `TELEGRAM_ALLOWED_USER_IDS` to run a task
- A way to exfiltrate `.env`, keys, or passwords through the bot
- A dangerous command that runs without the Allow prompt
- A crash or prompt that lets the agent keep clicking on the lock screen or a UAC dialog
