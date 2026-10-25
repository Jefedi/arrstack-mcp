"""Jellystat tools (Jellyfin watch statistics).

Checked against Jellystat 1.1.12 (backend/routes/*.js, server.js):
* Auth: x-api-token header (do NOT send an Authorization header with it).
* Errors are often HTTP 503 with a text body.
* getMostViewedByType fails if `days` is omitted, so it is always sent.
* /sync/begin*Sync keeps the HTTP request open until the sync ends (long timeout).
"""

from __future__ import annotations

from . import _http


def _hours(seconds) -> str:
    try:
        return f"{int(seconds) / 3600:.1f} h"
    except (TypeError, ValueError):
        return "?"


def register(mcp, server):
    settings = server.SETTINGS
    url = settings.get("JELLYSTAT_URL", "").rstrip("/")
    key = settings.get("JELLYSTAT_API_KEY", "")

    def call(path, method="GET", json=None, params=None, timeout=30, expect_json=True):
        headers = {"x-api-token": key} if key else {}
        return _http.request(server, "Jellystat", url, path, method=method, headers=headers,
                             json=json, params=params, timeout=timeout, expect_json=expect_json)

    @mcp.tool()
    def jellystat_overview(days: int = 30) -> str:
        """Top movies and series, most active users and DirectPlay-vs-Transcode counts over N days."""
        days = max(1, days)
        lines = [f"Jellystat — last {days} days"]
        for media in ("Movie", "Series"):
            data = call("/stats/getMostViewedByType", method="POST", json={"type": media, "days": days})
            if _http.is_error(data):
                return data
            lines.append(f"Most watched {media.lower()}s:")
            for item in data or []:
                lines.append(f"  • {item.get('Name', '?')}: {item.get('Plays', '?')} plays, "
                             f"{_hours(item.get('total_playback_duration'))}")
        users = call("/stats/getMostActiveUsers", method="POST", json={"days": days})
        if isinstance(users, list):
            lines.append("Most active users: " + ", ".join(
                f"{u.get('Name', '?')} ({u.get('Plays', '?')})" for u in users) or "none")
        methods = call("/stats/getPlaybackMethodStats", method="POST", json={"days": days})
        if isinstance(methods, list):
            lines.append("Play methods: " + ", ".join(
                f"{m.get('Name', '?')}: {m.get('Count', '?')}" for m in methods) or "none")
        return "\n".join(lines)

    @mcp.tool()
    def jellystat_history(search: str = "", user: str = "", limit: int = 20) -> str:
        """Latest plays recorded by Jellystat (grouped per item and user), newest first.

        Args:
            search: Optional text to match (title, user, client...).
            user: Optional exact Jellyfin user name.
            limit: Max rows (default 20).
        """
        import json as _json

        params = {"size": max(1, min(limit, 200)), "page": 1, "sort": "ActivityDateInserted", "desc": "true"}
        if search.strip():
            params["search"] = search.strip()
        if user.strip():
            params["filters"] = _json.dumps([{"field": "UserName", "value": user.strip()}])
        data = call("/api/getHistory", params=params)
        if _http.is_error(data):
            return data
        lines = []
        for row in (data or {}).get("results", []):
            lines.append(f"• {(row.get('ActivityDateInserted') or '?')[:16].replace('T', ' ')} | "
                         f"{row.get('UserName', '?')} | {row.get('FullName') or row.get('NowPlayingItemName', '?')} | "
                         f"{row.get('Client', '?')} | {row.get('PlayMethod', '?')} | "
                         f"{row.get('TotalPlays', 1)} play(s), {_hours(row.get('PlaybackDuration'))}")
        return "\n".join(lines) or "No history."

    @mcp.tool()
    def jellystat_users() -> str:
        """Every Jellyfin user with total plays, total watch time, last item watched and last client."""
        data = call("/stats/getAllUserActivity")
        if _http.is_error(data):
            return data
        lines = [f"• {u.get('UserName', '?')}: {u.get('TotalPlays', 0)} plays, {_hours(u.get('TotalWatchTime'))}"
                 f" — last: {u.get('LastWatched') or '-'} on {u.get('LastClient') or '-'}"
                 for u in data or []]
        return "\n".join(lines) or "No users."

    @mcp.tool()
    def jellystat_libraries() -> str:
        """Jellyfin libraries as seen by Jellystat, with item / season / episode counts."""
        data = call("/stats/getLibraryOverview")
        if _http.is_error(data):
            return data
        lines = [f"• {lib.get('Name', '?')} ({lib.get('CollectionType') or '?'}): {lib.get('Library_Count', 0)} items"
                 f"{', ' + str(lib.get('Season_Count')) + ' seasons' if lib.get('Season_Count') else ''}"
                 f"{', ' + str(lib.get('Episode_Count')) + ' episodes' if lib.get('Episode_Count') else ''}"
                 for lib in data or []]
        return "\n".join(lines) or "No libraries."

    @mcp.tool()
    def jellystat_sync(full: bool = False) -> str:
        """Re-sync Jellystat with Jellyfin. Waits until the sync ends (can take minutes).

        Args:
            full: true for a full sync, false (default) for recently added items only.
        """
        path = "/sync/beginSync" if full else "/sync/beginPartialSync"
        result = call(path, timeout=900, expect_json=False)
        if _http.is_error(result):
            return result
        return f"✅ {'Full' if full else 'Partial'} sync finished."

    return set()
