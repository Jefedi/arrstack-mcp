"""Dispatcharr tools (IPTV: channels, M3U / EPG sources, live streams, plugins).

Checked against Dispatcharr v0.33.0:
* Auth: static key in X-API-Key (acts as the key's owner — use an admin's key).
  10 failed attempts per minute per IP trip a rate limit.
* DRF routes need the trailing slash; /proxy/ts/* routes must NOT have one.
* /api/channels/channels/ is only paginated when page/page_size is sent.
* channel_group filters by exact group NAME. Stop/status calls use the channel UUID.
* No "refresh all EPG" endpoint: refresh one source at a time.
* Plugins live under /api/plugins/plugins/ (doubled on purpose upstream).
"""

from __future__ import annotations

from . import _http


def register(mcp, server):
    settings = server.SETTINGS
    url = settings.get("DISPATCHARR_URL", "").rstrip("/")
    key = settings.get("DISPATCHARR_API_KEY", "")

    def call(path, method="GET", json=None, params=None):
        headers = {"X-API-Key": key} if key else {}
        return _http.request(server, "Dispatcharr", url, path, method=method, headers=headers,
                             json=json, params=params, timeout=60)

    @mcp.tool()
    def dispatcharr_active_streams() -> str:
        """Live channels being watched right now: viewers, codec, resolution, bitrate, health."""
        data = call("/proxy/ts/status")
        if _http.is_error(data):
            return data
        channels = data.get("channels", []) if isinstance(data, dict) else []
        version = call("/api/core/version/")
        head = f"Dispatcharr {version.get('version', '?')}: " if isinstance(version, dict) else ""
        lines = [f"{head}{len(channels)} active channel(s)."]
        for c in channels:
            clients = c.get("clients") or []
            lines.append(f"• {c.get('channel_name', '?')} [uuid {c.get('channel_id')}] — {c.get('state', '?')}, "
                         f"{c.get('client_count', len(clients))} viewer(s), {c.get('resolution', '?')} "
                         f"{c.get('video_codec', '')}, {c.get('avg_bitrate', '?')}, "
                         f"{'healthy' if c.get('healthy', True) else 'UNHEALTHY'}, stream: {c.get('stream_name', '?')}")
            for cl in clients:
                lines.append(f"    - client {cl.get('client_id')} {cl.get('ip_address', '?')} "
                             f"({cl.get('user_agent', '?')[:40]})")
        return "\n".join(lines)

    @mcp.tool()
    def dispatcharr_stop(channel_uuid: str, client_id: str = "") -> str:
        """Stop a live channel for everyone, or disconnect one client from it.

        Args:
            channel_uuid: Channel UUID from dispatcharr_active_streams (not the channel number).
            client_id: Optional client id to disconnect only that viewer.
        """
        if not channel_uuid.strip():
            return "Give the channel UUID."
        if client_id.strip():
            data = call(f"/proxy/ts/stop_client/{channel_uuid.strip()}", method="POST",
                        json={"client_id": client_id.strip()})
        else:
            data = call(f"/proxy/ts/stop/{channel_uuid.strip()}", method="POST")
        if _http.is_error(data):
            return data
        return f"⏹️ {data.get('message', 'Stop requested.')}"

    @mcp.tool()
    def dispatcharr_channels(search: str = "", group: str = "", limit: int = 50) -> str:
        """Search Dispatcharr channels.

        Args:
            search: Text matched against channel name or group name.
            group: Exact group name(s), comma-separated (see dispatcharr_groups).
            limit: Max channels (default 50).
        """
        params = {"page": 1, "page_size": max(1, min(limit, 500)), "ordering": "channel_number"}
        if search.strip():
            params["search"] = search.strip()
        if group.strip():
            params["channel_group"] = group.strip()
        data = call("/api/channels/channels/", params=params)
        if _http.is_error(data):
            return data
        rows = data.get("results", []) if isinstance(data, dict) else data
        total = data.get("count", len(rows)) if isinstance(data, dict) else len(rows)
        lines = [f"{total} channel(s) match, showing {len(rows)}:"]
        for c in rows:
            name = c.get("effective_name") or c.get("name", "?")
            number = c.get("effective_channel_number") or c.get("channel_number")
            lines.append(f"• {number} {name} [id {c.get('id')}, uuid {c.get('uuid')}] — "
                         f"{len(c.get('streams') or [])} stream(s), EPG {'yes' if c.get('epg_data_id') else 'no'}")
        return "\n".join(lines)

    @mcp.tool()
    def dispatcharr_groups(name_contains: str = "") -> str:
        """Channel groups with their channel counts.

        Args:
            name_contains: Optional case-insensitive filter on the group name.
        """
        data = call("/api/channels/groups/")
        if _http.is_error(data):
            return data
        needle = name_contains.strip().lower()
        rows = [g for g in data or [] if needle in (g.get("name") or "").lower()]
        lines = [f"• {g.get('name', '?')} [id {g.get('id')}]: {g.get('channel_count', 0)} channel(s)" for g in rows]
        return "\n".join(lines) or "No groups."

    @mcp.tool()
    def dispatcharr_sources() -> str:
        """M3U accounts (status, expiry) and EPG sources (status, last message)."""
        m3u = call("/api/m3u/accounts/")
        if _http.is_error(m3u):
            return m3u
        lines = ["M3U accounts:"]
        for a in m3u or []:
            lines.append(f"• [{a.get('id')}] {a.get('name', '?')} — {a.get('status', '?')}"
                         f"{'' if a.get('is_active') else ' (inactive)'}, max streams {a.get('max_streams', '?')}, "
                         f"expires {a.get('exp_date') or a.get('earliest_expiration') or '?'}"
                         f"{' — ' + a['last_message'] if a.get('last_message') else ''}")
        epg = call("/api/epg/sources/")
        if isinstance(epg, list):
            lines.append("EPG sources:")
            for s in epg:
                lines.append(f"• [{s.get('id')}] {s.get('name', '?')} ({s.get('source_type', '?')}) — "
                             f"{s.get('status', '?')}{'' if s.get('is_active') else ' (inactive)'}, "
                             f"{s.get('epg_data_count', '?')} EPG entries"
                             f"{' — ' + s['last_message'] if s.get('last_message') else ''}")
        return "\n".join(lines)

    @mcp.tool()
    def dispatcharr_refresh(kind: str, source_id: int = 0) -> str:
        """Refresh an M3U account or an EPG source (runs in the background).

        Args:
            kind: "m3u" or "epg".
            source_id: Id from dispatcharr_sources. 0 = every active source of that kind.
        """
        if kind == "m3u":
            path = f"/api/m3u/refresh/{source_id}/" if source_id > 0 else "/api/m3u/refresh/"
            data = call(path, method="POST")
            if _http.is_error(data):
                return data
            return f"🔄 {data.get('message', 'M3U refresh started.')}"
        if kind != "epg":
            return 'kind must be "m3u" or "epg".'
        if source_id > 0:
            ids = [source_id]
        else:
            sources = call("/api/epg/sources/")
            if _http.is_error(sources):
                return sources
            ids = [s["id"] for s in sources or [] if s.get("is_active") and s.get("source_type") != "dummy"]
        results = []
        for sid in ids:
            data = call("/api/epg/import/", method="POST", json={"id": sid, "force": False})
            results.append(f"source {sid}: {data if _http.is_error(data) else 'refresh started'}")
        return "🔄 EPG — " + "; ".join(results) if results else "No active EPG source to refresh."

    @mcp.tool()
    def dispatcharr_plugins() -> str:
        """Installed Dispatcharr plugins, whether enabled, and the actions each one offers."""
        data = call("/api/plugins/plugins/")
        if _http.is_error(data):
            return data
        lines = []
        for p in data.get("plugins", []):
            actions = ", ".join(a.get("id", "?") if isinstance(a, dict) else str(a) for a in p.get("actions") or [])
            lines.append(f"• {p.get('name', '?')} [{p.get('key')}] v{p.get('version', '?')} — "
                         f"{'enabled' if p.get('enabled') else 'disabled'}"
                         f"{' — actions: ' + actions if actions else ''}")
        return "\n".join(lines) or "No plugins."

    @mcp.tool()
    def dispatcharr_run_plugin(plugin_key: str, action: str) -> str:
        """Run one action of an enabled plugin (e.g. a checker or an EPG clean-up).
        Plugin actions can change channels: describe the effect to the user first.

        Args:
            plugin_key: Plugin key from dispatcharr_plugins.
            action: Action id from dispatcharr_plugins.
        """
        if not plugin_key.strip() or not action.strip():
            return "Give plugin_key and action."
        data = call(f"/api/plugins/plugins/{plugin_key.strip()}/run/", method="POST",
                    json={"action": action.strip(), "params": {}})
        if _http.is_error(data):
            return data
        result = data.get("result")
        return f"✅ {plugin_key}.{action} ran.{' Result: ' + str(result)[:1500] if result else ''}"

    return set()
