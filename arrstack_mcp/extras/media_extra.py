"""Extra Seerr, Jellyfin and qBittorrent tools.

Checked against:
* Seerr  — seerr-api.yml (POST /request has `is4k`; POST /request/{id}/{status}).
* Jellyfin — Jellyfin.Api/Controllers: SessionController `GET Sessions`,
  UserController `GET Users`, ItemsController `GET Items` (searchTerm, recursive).
* qBittorrent 5.1.4 — src/webui/api/torrentscontroller.h: categories, setCategory,
  recheck, reannounce actions.
"""

from __future__ import annotations


def register(mcp, server):
    seerr = server._seerr
    jellyfin = server._jellyfin
    qbt = server._qbt

    # ── Seerr ──

    @mcp.tool()
    def seerr_request_4k(tmdb_id: int, media_type: str = "movie", seasons: str = "all") -> str:
        """Request the 4K version of a movie or show in Seerr (sent to the 4K Radarr/Sonarr servers).

        Args:
            tmdb_id: TMDB id (use seerr_search).
            media_type: "movie" or "tv".
            seasons: For TV only: "all" or a comma-separated list such as "1,2".
        """
        if tmdb_id <= 0:
            return "Invalid tmdb_id."
        if media_type not in ("movie", "tv"):
            return 'media_type must be "movie" or "tv".'
        body: dict = {"mediaType": media_type, "mediaId": tmdb_id, "is4k": True}
        if media_type == "tv":
            if seasons.strip().lower() == "all":
                body["seasons"] = "all"
            else:
                try:
                    body["seasons"] = [int(s) for s in seasons.split(",") if s.strip()]
                except ValueError:
                    return 'Invalid seasons. Use "all" or a list like "1,2,3".'
                if not body["seasons"]:
                    return 'Invalid seasons. Use "all" or a list like "1,2,3".'
        data = seerr("/request", method="POST", json=body)
        if isinstance(data, str):
            return data
        return f"✅ 4K request sent (tmdbId {tmdb_id}). Request id: {data.get('id', '?')}, status: {data.get('status', '?')}."

    @mcp.tool()
    def seerr_moderate_request(request_id: int, decision: str) -> str:
        """Approve or decline a pending Seerr request.

        Args:
            request_id: Seerr request id (use seerr_list_requests).
            decision: "approve" or "decline".
        """
        if request_id <= 0:
            return "Invalid request_id."
        if decision not in ("approve", "decline"):
            return 'decision must be "approve" or "decline".'
        data = seerr(f"/request/{request_id}/{decision}", method="POST")
        if isinstance(data, str):
            return data
        return f"✅ Request {request_id}: {decision}d."

    @mcp.tool()
    def seerr_delete_request(request_id: int) -> str:
        """Delete a Seerr request (does not delete any downloaded media)."""
        if request_id <= 0:
            return "Invalid request_id."
        data = seerr(f"/request/{request_id}", method="DELETE")
        if isinstance(data, str) and data.strip():
            return data
        return f"🗑️ Request {request_id} deleted."

    # ── Jellyfin ──

    @mcp.tool()
    def jellyfin_sessions(active_minutes: int = 15) -> str:
        """Who is watching what right now on Jellyfin, with the play method
        (DirectPlay / DirectStream / Transcode) and the transcode reasons if any.

        Args:
            active_minutes: Only sessions active in the last N minutes (default 15).
        """
        data = jellyfin("/Sessions", params={"activeWithinSeconds": max(1, active_minutes) * 60})
        if isinstance(data, str):
            return data
        lines = []
        for s in data:
            item = s.get("NowPlayingItem")
            who = f"{s.get('UserName', '?')} on {s.get('Client', '?')} ({s.get('DeviceName', '?')})"
            if not item:
                lines.append(f"• {who}: idle")
                continue
            title = item.get("Name", "?")
            if item.get("SeriesName"):
                title = (f"{item['SeriesName']} S{item.get('ParentIndexNumber') or 0:02d}"
                         f"E{item.get('IndexNumber') or 0:02d} — {title}")
            state = s.get("PlayState") or {}
            method = state.get("PlayMethod", "?")
            paused = " ⏸️" if state.get("IsPaused") else ""
            info = s.get("TranscodingInfo") or {}
            reasons = ", ".join(info.get("TranscodeReasons") or [])
            extra = f" — reasons: {reasons}" if reasons else ""
            lines.append(f"• {who}: {title} [{method}{extra}]{paused}")
        return "\n".join(lines) or "Nobody is connected."

    @mcp.tool()
    def jellyfin_users() -> str:
        """List Jellyfin users with admin flag, disabled flag and last activity."""
        data = jellyfin("/Users")
        if isinstance(data, str):
            return data
        lines = []
        for u in data:
            policy = u.get("Policy") or {}
            flags = [f for f, on in (("admin", policy.get("IsAdministrator")),
                                     ("disabled", policy.get("IsDisabled"))) if on]
            lines.append(f"• {u.get('Name', '?')} [{u.get('Id', '?')}]"
                         f"{' (' + ', '.join(flags) + ')' if flags else ''} — last active "
                         f"{(u.get('LastActivityDate') or 'never')[:16].replace('T', ' ')}")
        return "\n".join(lines) or "No users."

    @mcp.tool()
    def jellyfin_search(term: str, item_types: str = "Movie,Series", limit: int = 20) -> str:
        """Search the Jellyfin library.

        Args:
            term: Text to look for in titles.
            item_types: Comma-separated Jellyfin types (Movie, Series, Episode, MusicAlbum...).
            limit: Max results (default 20).
        """
        if not term.strip():
            return "Give a search term."
        data = jellyfin("/Items", params={"searchTerm": term, "recursive": "true",
                                          "includeItemTypes": item_types, "limit": max(1, min(limit, 100)),
                                          "fields": "Path,ProductionYear"})
        if isinstance(data, str):
            return data
        lines = [f"• {i.get('Name', '?')} ({i.get('ProductionYear', '?')}) [{i.get('Type', '?')}] "
                 f"{i.get('Path', '')}" for i in data.get("Items", [])]
        return "\n".join(lines) or "Nothing found."

    # ── qBittorrent ──

    def _hashes(value: str) -> str | None:
        value = value.strip()
        return value or None

    @mcp.tool()
    def qbt_categories() -> str:
        """List qBittorrent categories and their save paths."""
        data = qbt("/torrents/categories")
        if isinstance(data, str):
            return data
        lines = [f"• {name}: {(cat or {}).get('savePath') or '(default path)'}" for name, cat in data.items()]
        return "\n".join(lines) or "No categories."

    @mcp.tool()
    def qbt_set_category(torrent_hash: str, category: str) -> str:
        """Move torrents to a category (the *arr apps import by category).

        Args:
            torrent_hash: Hash, or several as "hash1|hash2".
            category: Existing category name (see qbt_categories); empty string removes it.
        """
        hashes = _hashes(torrent_hash)
        if not hashes or hashes == "all":
            return "Give explicit torrent hashes (not 'all')."
        result = qbt("/torrents/setCategory", method="POST", data={"hashes": hashes, "category": category})
        return "✅ Category set." if server._action_ok(result) else f"❌ Failed: {result}"

    @mcp.tool()
    def qbt_recheck(torrent_hash: str) -> str:
        """Force a hash recheck (verifies data on disk; does not start the torrent).

        Args:
            torrent_hash: Hash, or several as "hash1|hash2".
        """
        hashes = _hashes(torrent_hash)
        if not hashes or hashes == "all":
            return "Give explicit torrent hashes (not 'all')."
        result = qbt("/torrents/recheck", method="POST", data={"hashes": hashes})
        return "🔁 Recheck started." if server._action_ok(result) else f"❌ Failed: {result}"

    @mcp.tool()
    def qbt_reannounce(torrent_hash: str) -> str:
        """Force a tracker reannounce for torrents (useful when peers are missing).

        Args:
            torrent_hash: Hash, or several as "hash1|hash2".
        """
        hashes = _hashes(torrent_hash)
        if not hashes or hashes == "all":
            return "Give explicit torrent hashes (not 'all')."
        result = qbt("/torrents/reannounce", method="POST", data={"hashes": hashes})
        return "📣 Reannounced." if server._action_ok(result) else f"❌ Failed: {result}"

    return {"seerr_delete_request"}
