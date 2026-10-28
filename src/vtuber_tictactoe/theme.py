"""Saved overlay colors, constrained to plain hex values at the HTTP boundary."""

import re

DEFAULT_THEME = {
    "grid": "#e4d3ff",
    "numbers": "#f6eeff",
    "streamer": "#ff91c9",
    "chat": "#7df4dd",
    "banner_bg": "#9c5bea",
    "banner_text": "#ffffff",
}


def validate_theme(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(DEFAULT_THEME):
        raise ValueError("Choose all six overlay colors.")
    result: dict[str, str] = {}
    for key in DEFAULT_THEME:
        color = value[key]
        if not isinstance(color, str) or re.fullmatch(r"#[0-9a-fA-F]{6}", color) is None:
            raise ValueError("Colors must be six-digit hex values, such as #aabbcc.")
        result[key] = color.lower()
    return result
