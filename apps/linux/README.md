# Linux

Same OpenCtrl agent as Windows. This folder is the Linux desktop: `xdotool` and `wmctrl` on X11, bash for `run_shell`.

```sh
cp .env.example .env
sh run.sh
```

Install `xdotool`, `wmctrl`, `scrot` or ImageMagick, and `xclip`. Wayland often blocks synthetic clicks. The agent says so instead of pretending the click landed. The screen has to stay unlocked.
