"""Watchman — Slice 2 selection/suppression layer (no UI in this module)."""
from .select import select, reset_satisfied  # noqa: F401
from .trend import build_trend  # noqa: F401
from .config import DEFAULT_SELECTION, SelectionConfig  # noqa: F401
from .life_events import (apply_life_events, load_life_events,  # noqa: F401
                          add_life_event, list_life_events, delete_life_event,
                          default_effect_for, LIFE_EVENT_CATEGORIES, LIFE_EVENT_EFFECTS)
