"""Shared prompt-template loader for the ``prompts`` package.

The larger prompts live as ``.txt`` files next to this module so the prose stays
readable and diffable instead of being embedded as Python string literals. Each
template is read from disk once and cached for the process lifetime.
"""

import os
from functools import cache

_PROMPTS_DIR = os.path.dirname(os.path.abspath(__file__))


@cache
def load_template(name: str) -> str:
    """Read a ``.txt`` template from the prompts directory (cached after first read)."""
    with open(os.path.join(_PROMPTS_DIR, name), encoding="utf-8") as f:
        return f.read()
