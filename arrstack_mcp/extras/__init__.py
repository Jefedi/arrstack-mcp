"""Jefe's extra tools for arrstack-mcp (fork: Jefedi/arrstack-mcp).

Everything added by this fork lives in this package so upstream changes to
``server.py`` and ``config.py`` merge cleanly. The upstream files only carry
two small hooks:

* ``config.py`` registers the extra services (``services.build_services``).
* ``server.py`` calls ``load_extras(mcp)`` once all upstream tools exist and
  merges the returned names into ``DESTRUCTIVE_TOOLS``.

Each sub-module defines ``register(mcp, server)`` and returns the names of the
tools it added that delete data, so ``ALLOW_DESTRUCTIVE=false`` hides them too.
"""

from __future__ import annotations

import sys


def load_extras(mcp) -> frozenset[str]:
    """Register every extra tool on ``mcp``; return the destructive tool names."""
    # The server module is mid-import when this runs (it calls us from its
    # last lines), but every helper and setting above that point exists.
    server = sys.modules["arrstack_mcp.server"]

    from . import arr_extra, bazarr, crossseed, dispatcharr, gluetun, jellystat, media_extra, profilarr, wizarr

    destructive: set[str] = set()
    for module in (arr_extra, media_extra, bazarr, crossseed, gluetun, jellystat, wizarr, dispatcharr, profilarr):
        destructive |= set(module.register(mcp, server) or ())
    return frozenset(destructive)
