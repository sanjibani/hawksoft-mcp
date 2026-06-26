"""HawkSoft LogAction enum (subset used by MCP tools).

Maps the LogAction integer values from the Partner API v3.0 docs to human-readable
names. Agents should reference these by name (``"Phone To Insured"``) — the server
translates to the integer before sending.

Source: https://partner.hawksoft.app/v3/api.html#LogAction
"""
from __future__ import annotations

# Format: value -> (label, category)
LOG_ACTIONS: dict[int, tuple[str, str]] = {
    1: ("Phone To Insured", "Phone"),
    2: ("Phone To Carrier", "Phone"),
    3: ("Phone To Agency Staff", "Phone"),
    4: ("Phone To 3rd Party", "Phone"),
    5: ("Phone From Insured", "Phone"),
    6: ("Phone From Carrier", "Phone"),
    7: ("Phone From Agency Staff", "Phone"),
    8: ("Phone From 3rd Party", "Phone"),
    9: ("Mail To Insured", "Mail"),
    10: ("Mail To Carrier", "Mail"),
    11: ("Mail To Agency Staff", "Mail"),
    12: ("Mail To 3rd Party", "Mail"),
    13: ("Mail From Insured", "Mail"),
    14: ("Mail From Carrier", "Mail"),
    15: ("Mail From Agency Staff", "Mail"),
    16: ("Mail From 3rd Party", "Mail"),
    17: ("Walk In To Insured", "Walk In"),
    18: ("Walk In To Carrier", "Walk In"),
    19: ("Walk In To Agency Staff", "Walk In"),
    20: ("Walk In To 3rd Party", "Walk In"),
    21: ("Walk In From Insured", "Walk In"),
    22: ("Walk In From Carrier", "Walk In"),
    23: ("Walk In From Agency Staff", "Walk In"),
    24: ("Walk In From 3rd Party", "Walk In"),
    25: ("Online To Insured", "Online"),
    26: ("Online To Carrier", "Online"),
    27: ("Online To Agency Staff", "Online"),
    28: ("Online To 3rd Party", "Online"),
    29: ("Online From Insured", "Online"),
    30: ("Online From Carrier", "Online"),
    31: ("Online From Agency Staff", "Online"),
    32: ("Online From 3rd Party", "Online"),
    33: ("Email To Insured", "Email"),
    34: ("Email To Carrier", "Email"),
    35: ("Email To Agency Staff", "Email"),
    36: ("Email To 3rd Party", "Email"),
    37: ("Email From Insured", "Email"),
    38: ("Email From Carrier", "Email"),
    39: ("Email From Agency Staff", "Email"),
    40: ("Email From 3rd Party", "Email"),
    41: ("Text To Insured", "Text"),
    42: ("Text To Carrier", "Text"),
    43: ("Text To Agency Staff", "Text"),
    44: ("Text To 3rd Party", "Text"),
    45: ("Text From Insured", "Text"),
    46: ("Text From Carrier", "Text"),
    47: ("Text From Agency Staff", "Text"),
    48: ("Text From 3rd Party", "Text"),
    49: ("Chat To Insured", "Chat"),
    50: ("Chat To Carrier", "Chat"),
    51: ("Chat To Agency Staff", "Chat"),
    52: ("Chat To 3rd Party", "Chat"),
    53: ("Chat From Insured", "Chat"),
    54: ("Chat From Carrier", "Chat"),
    55: ("Chat From Agency Staff", "Chat"),
    56: ("Chat From 3rd Party", "Chat"),
}

# Reverse lookup: name (case-insensitive) -> value
LOG_ACTIONS_BY_NAME: dict[str, int] = {label.lower(): v for v, (label, _) in LOG_ACTIONS.items()}


def resolve_channel(channel: str | int) -> int:
    """Resolve a friendly channel name to its HawkSoft LogAction integer.

    Accepts either an integer (passes through) or a string like "phone to insured",
    "Email From Carrier", etc. (case-insensitive).

    Raises ValueError if the name is not recognised.
    """
    if isinstance(channel, int):
        if channel not in LOG_ACTIONS:
            raise ValueError(
                f"Unknown LogAction integer {channel}. Valid range: 1-{max(LOG_ACTIONS)}."
            )
        return channel
    key = channel.strip().lower()
    if key not in LOG_ACTIONS_BY_NAME:
        valid = sorted({label for label, _ in LOG_ACTIONS.values()})
        raise ValueError(
            f"Unknown channel name {channel!r}. Valid names: {valid}"
        )
    return LOG_ACTIONS_BY_NAME[key]


def list_channels() -> list[dict[str, str | int]]:
    """Return all channels as ``[{"value": int, "label": str, "category": str}, ...]``."""
    return [
        {"value": v, "label": label, "category": cat}
        for v, (label, cat) in sorted(LOG_ACTIONS.items())
    ]