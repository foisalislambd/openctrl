# Changelog

## 1.1.0

- A desktop window for setup, start and stop, and the log. The agent starts with the app.
- Bot token, API key, and the other settings are stored in `data/openctrl.db`. An existing `.env` is copied once.
- GitHub Actions publishes a release when the root `VERSION` file is greater than the latest release tag, with Windows, macOS, and Linux builds.

## 1.0.0

- Control a Windows desktop from a private Telegram chat.
- Prefer the accessibility tree, and take a screenshot only when a control has no usable name.
- Confirm disk format, shutdown, registry deletes, and recursive deletes of system paths.
- Voice notes, file upload and send-back, delayed tasks, notes between tasks, and a login shortcut.
