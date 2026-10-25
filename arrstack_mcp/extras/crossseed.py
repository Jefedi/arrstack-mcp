"""cross-seed daemon tools (v6, REST).

Checked against cross-seed v6.13.9 (src/server.ts):
* GET  /api/ping     — no auth, "OK"
* GET  /api/status   — auth, "OK"
* POST /api/webhook  — exactly one of infoHash/path; answers 204 *before* searching
* POST /api/job      — name in rss|search|updateIndexerCaps|inject|cleanup
Auth: X-Api-Key header. Bodies are strict: unknown keys give HTTP 400.
"""

from __future__ import annotations

import re

from . import _http

JOBS = ("rss", "search", "updateIndexerCaps", "inject", "cleanup")


def register(mcp, server):
    settings = server.SETTINGS
    url = settings.get("CROSSSEED_URL", "").rstrip("/")
    key = settings.get("CROSSSEED_API_KEY", "")

    def call(path, method="GET", json=None):
        headers = {"X-Api-Key": key} if key else {}
        return _http.request(server, "cross-seed", url, path, method=method, headers=headers,
                             json=json, expect_json=False)

    @mcp.tool()
    def crossseed_status() -> str:
        """Check that the cross-seed daemon is up and that the API key is accepted."""
        ping = call("/api/ping")
        if _http.is_error(ping):
            return ping
        status = call("/api/status")
        if _http.is_error(status):
            return f"Daemon is up, but the API key was refused: {status}"
        return "✅ cross-seed daemon is up and the API key works."

    @mcp.tool()
    def crossseed_search_torrent(info_hash: str = "", path: str = "", include_single_episodes: bool = False) -> str:
        """Ask cross-seed to look for cross-seeds of ONE torrent already in the client.

        The daemon answers immediately and searches in the background; the number of
        matches only appears in the cross-seed logs.

        Args:
            info_hash: 40-character info hash of the local torrent (see qbt_list_torrents).
            path: Or a path to the data, as seen by the cross-seed container. Give one, not both.
            include_single_episodes: Also match single-episode torrents.
        """
        info_hash = info_hash.strip().lower()
        path = path.strip()
        if bool(info_hash) == bool(path):
            return "Give exactly one of info_hash or path."
        if info_hash and not re.fullmatch(r"[0-9a-f]{40}", info_hash):
            return "info_hash must be 40 hexadecimal characters."
        body = {"infoHash": info_hash} if info_hash else {"path": path}
        if include_single_episodes:
            body["includeSingleEpisodes"] = True
        result = call("/api/webhook", method="POST", json=body)
        if _http.is_error(result):
            return result
        return "🔎 Search queued. Results are written to the cross-seed logs (no API returns them)."

    @mcp.tool()
    def crossseed_run_job(name: str) -> str:
        """Run a cross-seed job now instead of waiting for its schedule.

        Args:
            name: rss, search, updateIndexerCaps, inject or cleanup. "inject" adds matched
                torrents to qBittorrent — ask the user first. A job disabled in the
                config answers 404; a job already running (or just triggered manually) answers 409.
        """
        if name not in JOBS:
            return f"Unknown job. Use one of: {', '.join(JOBS)}."
        result = call("/api/job", method="POST", json={"name": name})
        if _http.is_error(result):
            return result
        return f"▶️ {result.strip() or name + ' started'}"

    return set()
