"""Extra Sonarr / Radarr tools: health, history, wanted, blocklist, commands, deletion.

Endpoints checked against the upstream OpenAPI specs
(Sonarr src/Sonarr.Api.V3/openapi.json, Radarr src/Radarr.Api.V3/openapi.json)
and command field names against the *Command.cs classes.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# Commands the agent may start. Name -> (id field, is the id a list?).
SONARR_COMMANDS = {
    "RefreshSeries": ("seriesIds", True),
    "RescanSeries": ("seriesId", False),
    "RenameSeries": ("seriesIds", True),
    "SeriesSearch": ("seriesId", False),
    "MissingEpisodeSearch": ("seriesId", False),
    "RssSync": (None, False),
}
RADARR_COMMANDS = {
    "RefreshMovie": ("movieIds", True),
    "RescanMovie": ("movieId", False),
    "RenameMovie": ("movieIds", True),
    "MoviesSearch": ("movieIds", True),
    "MissingMoviesSearch": (None, False),
    "CutoffUnmetMoviesSearch": (None, False),
    "RssSync": (None, False),
}


def _size(server, value) -> str:
    try:
        return server._format_size(int(value or 0))
    except (TypeError, ValueError):
        return "?"


def _health(server, call, name: str) -> str:
    status = call("/system/status")
    if isinstance(status, str):
        return status
    lines = [f"{name} {status.get('version', '?')} — {status.get('osName', '?')} "
             f"{status.get('osVersion', '')}".rstrip()]
    health = call("/health")
    if isinstance(health, list):
        if health:
            lines.append("Health issues:")
            for item in health:
                lines.append(f"• [{item.get('type', '?')}] {item.get('source', '?')}: {item.get('message', '')}")
        else:
            lines.append("Health: no issues.")
    disks = call("/diskspace")
    if isinstance(disks, list) and disks:
        lines.append("Disk space:")
        for disk in disks:
            lines.append(f"• {disk.get('path', '?')}: {_size(server, disk.get('freeSpace'))} free "
                         f"of {_size(server, disk.get('totalSpace'))}")
    return "\n".join(lines)


def _command(call, commands: dict, name: str, item_id: int, label: str) -> str:
    if name not in commands:
        return f"Unknown command '{name}'. Allowed: {', '.join(commands)}."
    field, as_list = commands[name]
    body: dict = {"name": name}
    if field and item_id > 0:
        body[field] = [item_id] if as_list else item_id
    elif field and not name.startswith("Missing"):
        return f"{name} needs a {label} id."
    data = call("/command", method="POST", json=body)
    if isinstance(data, str):
        return data
    return f"✅ {name} queued (command id {data.get('id', '?')}, status {data.get('status', '?')})."


def _page(data) -> list:
    if isinstance(data, dict):
        return data.get("records", []) or []
    return []


def register(mcp, server):
    sonarr = server._sonarr
    radarr = server._radarr

    # ── Sonarr ──

    @mcp.tool()
    def sonarr_health() -> str:
        """Sonarr version, health warnings (indexers, download client, disk...) and free disk space."""
        return _health(server, sonarr, "Sonarr")

    @mcp.tool()
    def sonarr_history(limit: int = 20, event_type: str = "", series_id: int = 0) -> str:
        """Recent Sonarr history (grabs, imports, failures, deletions), newest first.

        Args:
            limit: Number of events (1-100, default 20).
            event_type: Optional filter: grabbed, downloadFolderImported, downloadFailed,
                episodeFileDeleted, episodeFileRenamed, downloadIgnored.
            series_id: Optional Sonarr series id to restrict to one show.
        """
        params = {"page": 1, "pageSize": max(1, min(limit, 100)), "sortKey": "date",
                  "sortDirection": "descending", "includeSeries": "true", "includeEpisode": "true"}
        types = {"grabbed": 1, "downloadFolderImported": 3, "downloadFailed": 4,
                 "episodeFileDeleted": 5, "episodeFileRenamed": 6, "downloadIgnored": 7}
        if event_type:
            if event_type not in types:
                return f"Unknown event_type. Use one of: {', '.join(types)}."
            params["eventType"] = types[event_type]
        if series_id > 0:
            params["seriesIds"] = series_id
        data = sonarr("/history", params=params)
        if isinstance(data, str):
            return data
        lines = []
        for rec in _page(data):
            series = (rec.get("series") or {}).get("title", "?")
            ep = rec.get("episode") or {}
            quality = ((rec.get("quality") or {}).get("quality") or {}).get("name", "?")
            lines.append(
                f"• {(rec.get('date') or '?')[:16].replace('T', ' ')} | {rec.get('eventType', '?')} | "
                f"{series} S{ep.get('seasonNumber', 0):02d}E{ep.get('episodeNumber', 0):02d} | {quality}\n"
                f"  {rec.get('sourceTitle', '')}"
            )
        return "\n".join(lines) or "No history."

    @mcp.tool()
    def sonarr_wanted(kind: str = "missing", limit: int = 20) -> str:
        """Monitored episodes that are missing, or below the quality cutoff.

        Args:
            kind: "missing" (default) or "cutoff" (has a file but below the profile cutoff).
            limit: Number of episodes (1-100, default 20).
        """
        if kind not in ("missing", "cutoff"):
            return 'kind must be "missing" or "cutoff".'
        data = sonarr(f"/wanted/{kind}", params={
            "page": 1, "pageSize": max(1, min(limit, 100)), "sortKey": "airDateUtc",
            "sortDirection": "descending", "includeSeries": "true", "monitored": "true"})
        if isinstance(data, str):
            return data
        total = data.get("totalRecords", "?")
        lines = [f"{total} episode(s) {kind}. Showing {len(_page(data))}:"]
        for ep in _page(data):
            series = (ep.get("series") or {}).get("title", "?")
            lines.append(f"• {series} S{ep.get('seasonNumber', 0):02d}E{ep.get('episodeNumber', 0):02d} "
                         f"\"{ep.get('title', '')}\" — aired {(ep.get('airDateUtc') or '?')[:10]} "
                         f"[seriesId {ep.get('seriesId', '?')}]")
        return "\n".join(lines)

    @mcp.tool()
    def sonarr_blocklist(limit: int = 20) -> str:
        """Releases Sonarr has blocklisted (will not grab again), newest first."""
        data = sonarr("/blocklist", params={"page": 1, "pageSize": max(1, min(limit, 100)),
                                            "sortKey": "date", "sortDirection": "descending"})
        if isinstance(data, str):
            return data
        lines = [f"• [{rec.get('id')}] {(rec.get('date') or '?')[:10]} {rec.get('sourceTitle', '?')} — "
                 f"{rec.get('message', '')}" for rec in _page(data)]
        return "\n".join(lines) or "Blocklist is empty."

    @mcp.tool()
    def sonarr_command(name: str, series_id: int = 0) -> str:
        """Start a Sonarr task.

        Args:
            name: One of RefreshSeries (re-read metadata), RescanSeries (re-scan files on disk),
                RenameSeries (apply the naming scheme), SeriesSearch (search every monitored episode),
                MissingEpisodeSearch (all missing episodes; series_id optional), RssSync.
            series_id: Sonarr series id (use sonarr_list_series). Not needed for RssSync.
        """
        return _command(sonarr, SONARR_COMMANDS, name, series_id, "series")

    @mcp.tool()
    def sonarr_delete_series(series_id: int, delete_files: bool = False, add_exclusion: bool = False) -> str:
        """Remove a series from Sonarr. DESTRUCTIVE when delete_files is true.

        Args:
            series_id: Sonarr series id.
            delete_files: Also delete the series folder and every episode file on disk.
            add_exclusion: Prevent import lists from adding it back.
        """
        if series_id <= 0:
            return "Invalid series_id."
        series = sonarr(f"/series/{series_id}")
        if isinstance(series, str):
            return series
        tags = set(series.get("tags") or [])
        labels = server._tag_labels(sonarr)
        if any("keep" in (labels.get(t) or "").lower() for t in tags):
            return (f"⛔ {series.get('title')} carries a 'keep' tag (protected collection). "
                    "Remove the tag first if you really want to delete it.")
        result = sonarr(f"/series/{series_id}", method="DELETE", params={
            "deleteFiles": str(delete_files).lower(), "addImportListExclusion": str(add_exclusion).lower()})
        if isinstance(result, str) and result.strip():
            return result
        return f"🗑️ Removed {series.get('title')} from Sonarr (files deleted: {delete_files})."

    # ── Radarr ──

    @mcp.tool()
    def radarr_health() -> str:
        """Radarr version, health warnings (indexers, download client, disk...) and free disk space."""
        return _health(server, radarr, "Radarr")

    @mcp.tool()
    def radarr_history(limit: int = 20, event_type: str = "", movie_id: int = 0) -> str:
        """Recent Radarr history (grabs, imports, failures, deletions), newest first.

        Args:
            limit: Number of events (1-100, default 20).
            event_type: Optional filter: grabbed, downloadFolderImported, downloadFailed,
                movieFileDeleted, movieFileRenamed, downloadIgnored.
            movie_id: Optional Radarr movie id.
        """
        params = {"page": 1, "pageSize": max(1, min(limit, 100)), "sortKey": "date",
                  "sortDirection": "descending", "includeMovie": "true"}
        types = {"grabbed": 1, "downloadFolderImported": 3, "downloadFailed": 4,
                 "movieFileDeleted": 6, "movieFileRenamed": 8, "downloadIgnored": 9}
        if event_type:
            if event_type not in types:
                return f"Unknown event_type. Use one of: {', '.join(types)}."
            params["eventType"] = types[event_type]
        if movie_id > 0:
            params["movieIds"] = movie_id
        data = radarr("/history", params=params)
        if isinstance(data, str):
            return data
        lines = []
        for rec in _page(data):
            movie = (rec.get("movie") or {}).get("title", "?")
            quality = ((rec.get("quality") or {}).get("quality") or {}).get("name", "?")
            lines.append(f"• {(rec.get('date') or '?')[:16].replace('T', ' ')} | {rec.get('eventType', '?')} | "
                         f"{movie} | {quality}\n  {rec.get('sourceTitle', '')}")
        return "\n".join(lines) or "No history."

    @mcp.tool()
    def radarr_upcoming(days: int = 30) -> str:
        """Movies with a cinema, digital or physical release within the next N days (default 30)."""
        start = datetime.now().strftime("%Y-%m-%d")
        end = (datetime.now() + timedelta(days=max(1, days))).strftime("%Y-%m-%d")
        data = radarr("/calendar", params={"start": start, "end": end})
        if isinstance(data, str):
            return data
        lines = []
        for movie in data:
            dates = []
            for key, label in (("inCinemas", "cinema"), ("digitalRelease", "digital"),
                               ("physicalRelease", "physical")):
                if movie.get(key) and start <= movie[key][:10] <= end:
                    dates.append(f"{label} {movie[key][:10]}")
            lines.append(f"• {movie.get('title', '?')} ({movie.get('year', '?')}) — {', '.join(dates) or '?'}"
                         f"{' ✅ downloaded' if movie.get('hasFile') else ''}")
        return "\n".join(lines) or "Nothing upcoming."

    @mcp.tool()
    def radarr_wanted(kind: str = "missing", limit: int = 20) -> str:
        """Monitored movies that are missing, or below the quality cutoff.

        Args:
            kind: "missing" (default) or "cutoff".
            limit: Number of movies (1-100, default 20).
        """
        if kind not in ("missing", "cutoff"):
            return 'kind must be "missing" or "cutoff".'
        data = radarr(f"/wanted/{kind}", params={"page": 1, "pageSize": max(1, min(limit, 100)),
                                                 "sortKey": "movieMetadata.sortTitle",
                                                 "sortDirection": "ascending", "monitored": "true"})
        if isinstance(data, str):
            return data
        lines = [f"{data.get('totalRecords', '?')} movie(s) {kind}. Showing {len(_page(data))}:"]
        for movie in _page(data):
            lines.append(f"• {movie.get('title', '?')} ({movie.get('year', '?')}) [id {movie.get('id', '?')}]")
        return "\n".join(lines)

    @mcp.tool()
    def radarr_blocklist(limit: int = 20) -> str:
        """Releases Radarr has blocklisted (will not grab again), newest first."""
        data = radarr("/blocklist", params={"page": 1, "pageSize": max(1, min(limit, 100)),
                                            "sortKey": "date", "sortDirection": "descending"})
        if isinstance(data, str):
            return data
        lines = [f"• [{rec.get('id')}] {(rec.get('date') or '?')[:10]} {rec.get('sourceTitle', '?')} — "
                 f"{rec.get('message', '')}" for rec in _page(data)]
        return "\n".join(lines) or "Blocklist is empty."

    @mcp.tool()
    def radarr_command(name: str, movie_id: int = 0) -> str:
        """Start a Radarr task.

        Args:
            name: One of RefreshMovie, RescanMovie, RenameMovie, MoviesSearch (search one movie),
                MissingMoviesSearch, CutoffUnmetMoviesSearch, RssSync.
            movie_id: Radarr movie id (use radarr_list_movies). Not needed for the
                Missing/CutoffUnmet searches or RssSync.
        """
        return _command(radarr, RADARR_COMMANDS, name, movie_id, "movie")

    @mcp.tool()
    def radarr_delete_movie(movie_id: int, delete_files: bool = False, add_exclusion: bool = False) -> str:
        """Remove a movie from Radarr. DESTRUCTIVE when delete_files is true.

        Args:
            movie_id: Radarr movie id.
            delete_files: Also delete the movie folder and file on disk.
            add_exclusion: Prevent import lists from adding it back.
        """
        if movie_id <= 0:
            return "Invalid movie_id."
        movie = radarr(f"/movie/{movie_id}")
        if isinstance(movie, str):
            return movie
        labels = server._tag_labels(radarr)
        if any("keep" in (labels.get(t) or "").lower() for t in movie.get("tags") or []):
            return (f"⛔ {movie.get('title')} carries a 'keep' tag (protected collection). "
                    "Remove the tag first if you really want to delete it.")
        result = radarr(f"/movie/{movie_id}", method="DELETE", params={
            "deleteFiles": str(delete_files).lower(), "addImportExclusion": str(add_exclusion).lower()})
        if isinstance(result, str) and result.strip():
            return result
        return f"🗑️ Removed {movie.get('title')} from Radarr (files deleted: {delete_files})."

    return {"sonarr_delete_series", "radarr_delete_movie"}
