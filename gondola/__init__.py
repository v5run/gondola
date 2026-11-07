import os

# strftime flag for "no zero padding": %-d on Linux/macOS, %#d on Windows.
NP = "#" if os.name == "nt" else "-"


def clock(t: str | None) -> str | None:
    """'21:15' -> '9:15 pm' (times already in 12-hour form pass through)."""
    if not t or not isinstance(t, str) or len(t) < 5 or t[2] != ":" or not t[:2].isdigit():
        return t
    h, m = int(t[:2]), t[3:5]
    return f"{(h - 1) % 12 + 1}:{m} {'am' if h < 12 else 'pm'}"
