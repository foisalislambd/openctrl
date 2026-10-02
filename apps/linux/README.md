# Linux

Same OpenCtrl agent as Windows. This folder is the Linux desktop: `xdotool` and `wmctrl` on X11, bash for `run_shell`.

```sh
sh run.sh
```

The window stores the bot token and API key in `data/openctrl.db`. An existing `.env` is copied once.

Install `xdotool`, `wmctrl`, `scrot` or ImageMagick, and `xclip`. Wayland often blocks synthetic clicks. The agent says so instead of pretending the click landed. The screen has to stay unlocked.
