"""Turn chords like ctrl+shift+p into uiautomation SendKeys text."""

NAMED_KEYS = {
    "enter": "Enter",
    "return": "Enter",
    "esc": "Esc",
    "escape": "Esc",
    "tab": "Tab",
    "space": "Space",
    "backspace": "Back",
    "bksp": "Back",
    "delete": "Delete",
    "del": "Delete",
    "insert": "Insert",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "home": "Home",
    "end": "End",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "pgup": "PageUp",
    "pgdn": "PageDown",
    **{f"f{i}": f"F{i}" for i in range(1, 25)},
}

MODIFIERS = {
    "ctrl": "Ctrl",
    "control": "Ctrl",
    "alt": "Alt",
    "shift": "Shift",
    "win": "Win",
    "windows": "Win",
    "super": "Win",
}


def blocks_secure_attention(chord: str) -> bool:
    """Windows ignores a synthetic Ctrl+Alt+Delete. It is the secure attention sequence."""
    upper = chord.upper()
    return "{CTRL}" in upper and "{ALT}" in upper and "{DELETE}" in upper


def to_sendkeys(spec: str) -> str:
    text = (spec or "").strip()
    if not text:
        raise ValueError("No keys given.")
    if text.startswith("{") and "+" not in text:
        return text
    chunks = [part.strip() for part in text.split(",") if part.strip()]
    return "".join(_chunk(chunk) for chunk in chunks)


def _chunk(chunk: str) -> str:
    if "+" not in chunk:
        return _single(chunk)
    parts = [part.strip() for part in chunk.split("+") if part.strip()]
    if len(parts) < 2:
        raise ValueError(f"Incomplete chord: {chunk}")
    modifiers = parts[:-1]
    key = parts[-1]
    unknown = [name for name in modifiers if name.lower() not in MODIFIERS]
    if unknown:
        raise ValueError(f"Unknown modifier: {', '.join(unknown)}")
    held = "".join("{" + MODIFIERS[name.lower()] + "}" for name in modifiers)
    return held + _single(key)


def _single(key: str) -> str:
    lowered = key.lower()
    if lowered in NAMED_KEYS:
        return "{" + NAMED_KEYS[lowered] + "}"
    if len(key) == 1:
        return key
    raise ValueError(
        f"{key!r} is not a key. Use type_text for words, or a chord like ctrl+s."
    )
