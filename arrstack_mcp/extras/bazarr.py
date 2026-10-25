"""Bazarr tools (subtitles).

Checked against Bazarr v1.6.2 (bazarr/api/*). Notes from the source:
* Auth: X-API-KEY header. Base path: {url}/api.
* Booleans are the strings "True"/"False". Lists on GET are repeated `seriesid[]=`.
* Search/download actions are queued jobs: they answer 204 at once (see bazarr_jobs).
* PATCH /series|/movies action=search-wanted ignores the id and runs the global search.
* /api/badges counts missing subtitle *languages*, not items.
"""

from __future__ import annotations

from . import _http


def _tf(value: bool) -> str:
    return "True" if value else "False"


def register(mcp, server):
    settings = server.SETTINGS
    url = settings.get("BAZARR_URL", "").rstrip("/")
    key = settings.get("BAZARR_API_KEY", "")

    def call(path, method="GET", params=None, data=None):
        headers = {"X-API-KEY": key} if key else {}
        return _http.request(server, "Bazarr", url, f"/api{path}", method=method, headers=headers,
                             params=params, data=data, timeout=60)

    def _kind(kind: str):
        if kind in ("series", "episode", "episodes", "tv"):
            return "series"
        if kind in ("movie", "movies", "film"):
            return "movies"
        return None

    def _subs(items) -> str:
        return ", ".join(
            f"{s.get('code2') or s.get('name', '?')}{' forced' if s.get('forced') else ''}{' HI' if s.get('hi') else ''}"
            for s in items or []) or "none"

    @mcp.tool()
    def bazarr_status() -> str:
        """Bazarr version, linked Sonarr/Radarr versions, health issues and missing-subtitle counters."""
        status = call("/system/status")
        if _http.is_error(status):
            return status
        d = status.get("data", {}) if isinstance(status, dict) else {}
        lines = [f"Bazarr {d.get('bazarr_version', '?')} (Sonarr {d.get('sonarr_version', '?')}, "
                 f"Radarr {d.get('radarr_version', '?')}), started {d.get('start_time', '?')}"]
        badges = call("/badges")
        if isinstance(badges, dict):
            lines.append(f"Missing subtitle languages — episodes: {badges.get('episodes', '?')}, "
                         f"movies: {badges.get('movies', '?')}; throttled providers: {badges.get('providers', '?')}; "
                         f"Sonarr link: {badges.get('sonarr_signalr') or '-'}, Radarr link: {badges.get('radarr_signalr') or '-'}")
        health = call("/system/health")
        if isinstance(health, dict):
            issues = health.get("data") or []
            lines.append("Health: no issues." if not issues else "Health issues:")
            for issue in issues:
                lines.append(f"• {issue.get('object', '')} {issue.get('issue', issue)}".strip())
        return "\n".join(lines)

    @mcp.tool()
    def bazarr_wanted(kind: str = "series", limit: int = 25) -> str:
        """Episodes or movies that are missing subtitles.

        Args:
            kind: "series" (episodes) or "movies".
            limit: Max items (default 25).
        """
        k = _kind(kind)
        if not k:
            return 'kind must be "series" or "movies".'
        path = "/episodes/wanted" if k == "series" else "/movies/wanted"
        data = call(path, params={"start": 0, "length": max(1, min(limit, 200))})
        if _http.is_error(data):
            return data
        lines = [f"{data.get('total', '?')} {'episode' if k == 'series' else 'movie'}(s) missing subtitles:"]
        for item in data.get("data", []):
            if k == "series":
                lines.append(f"• {item.get('seriesTitle', '?')} {item.get('episode_number', '?')} "
                             f"\"{item.get('episodeTitle', '')}\" — missing {_subs(item.get('missing_subtitles'))} "
                             f"[seriesId {item.get('sonarrSeriesId')}, episodeId {item.get('sonarrEpisodeId')}]")
            else:
                lines.append(f"• {item.get('title', '?')} — missing {_subs(item.get('missing_subtitles'))} "
                             f"[radarrId {item.get('radarrId')}]")
        return "\n".join(lines)

    @mcp.tool()
    def bazarr_item_subtitles(kind: str, item_id: int) -> str:
        """Subtitles present and missing for one movie, or for every episode of one series.

        Args:
            kind: "series" or "movies".
            item_id: Sonarr series id or Radarr movie id (same ids as in Sonarr/Radarr).
        """
        k = _kind(kind)
        if not k or item_id <= 0:
            return 'Give kind ("series" or "movies") and a positive item_id.'
        if k == "series":
            data = call("/episodes", params={"seriesid[]": [item_id]})
        else:
            data = call("/movies", params={"radarrid[]": [item_id]})
        if _http.is_error(data):
            return data
        lines = []
        for item in data.get("data", []):
            if k == "series":
                head = f"S{item.get('season', 0):02d}E{item.get('episode', 0):02d} {item.get('title', '')}"
                ident = f"episodeId {item.get('sonarrEpisodeId')}"
            else:
                head = f"{item.get('title', '?')} ({item.get('year', '?')})"
                ident = f"radarrId {item.get('radarrId')}"
            have = "; ".join(f"{s.get('code2', '?')}{' forced' if s.get('forced') else ''}"
                             f"{' HI' if s.get('hi') else ''} → {s.get('path') or 'embedded'}"
                             for s in item.get("subtitles") or []) or "none"
            lines.append(f"• {head} [{ident}]\n  have: {have}\n  missing: {_subs(item.get('missing_subtitles'))}")
        return "\n".join(lines) or "Nothing found (is the id a Sonarr/Radarr id known to Bazarr?)."

    @mcp.tool()
    def bazarr_search_missing(kind: str, item_id: int = 0) -> str:
        """Search and download missing subtitles (queued in Bazarr's job list).

        Args:
            kind: "series" or "movies".
            item_id: Sonarr series id / Radarr movie id to search for ONE item.
                Leave 0 to run the global "wanted" search for every series (or every movie).
        """
        k = _kind(kind)
        if not k:
            return 'kind must be "series" or "movies".'
        id_field = "seriesid" if k == "series" else "radarrid"
        if item_id > 0:
            form = {id_field: item_id, "action": "search-missing"}
        else:
            form = {"action": "search-wanted"}
        result = call(f"/{k}", method="PATCH", data=form)
        if _http.is_error(result):
            return result
        scope = f"{id_field} {item_id}" if item_id > 0 else f"all {k}"
        return f"🔎 Subtitle search queued for {scope}. Follow it with bazarr_jobs."

    @mcp.tool()
    def bazarr_download_subtitle(kind: str, language: str, item_id: int, episode_id: int = 0,
                                 forced: bool = False, hearing_impaired: bool = False) -> str:
        """Search and download ONE subtitle language for one episode or movie (queued job).

        Args:
            kind: "series" or "movies".
            language: 2-letter code, e.g. "fr", "en", "sq".
            item_id: Sonarr series id (for an episode) or Radarr movie id.
            episode_id: Sonarr episode id (required for series; see bazarr_item_subtitles).
            forced: Forced (foreign parts only) subtitle.
            hearing_impaired: Hearing-impaired subtitle.
        """
        k = _kind(kind)
        if not k or item_id <= 0 or not language.strip():
            return "Give kind, language and a positive item_id."
        form = {"language": language.strip(), "forced": _tf(forced), "hi": _tf(hearing_impaired)}
        if k == "series":
            if episode_id <= 0:
                return "episode_id is required for series."
            form.update(seriesid=item_id, episodeid=episode_id)
            result = call("/episodes/subtitles", method="PATCH", data=form)
        else:
            form["radarrid"] = item_id
            result = call("/movies/subtitles", method="PATCH", data=form)
        if _http.is_error(result):
            return result
        return f"⬇️ Download queued ({language}). Follow it with bazarr_jobs."

    @mcp.tool()
    def bazarr_sync_subtitle(kind: str, item_id: int, language: str, path: str,
                             forced: bool = False, hearing_impaired: bool = False) -> str:
        """Re-synchronise an existing subtitle file with the video (Bazarr's subsync).

        Args:
            kind: "series" or "movies".
            item_id: Sonarr EPISODE id for series, Radarr movie id for movies.
            language: 2-letter code of the subtitle.
            path: Subtitle file path exactly as shown by bazarr_item_subtitles.
            forced: Forced subtitle.
            hearing_impaired: Hearing-impaired subtitle.
        """
        k = _kind(kind)
        if not k or item_id <= 0 or not path.strip():
            return "Give kind, item_id and the subtitle path."
        form = {"action": "sync", "language": language, "type": "episode" if k == "series" else "movie",
                "id": item_id, "path": path, "forced": _tf(forced), "hi": _tf(hearing_impaired)}
        result = call("/subtitles", method="PATCH", data=form)
        if _http.is_error(result):
            return result
        return "🔄 Sync started."

    @mcp.tool()
    def bazarr_delete_subtitle(kind: str, language: str, path: str, item_id: int, episode_id: int = 0,
                               forced: bool = False, hearing_impaired: bool = False) -> str:
        """Delete a subtitle file from disk. DESTRUCTIVE.

        Args:
            kind: "series" or "movies".
            language: 2-letter code.
            path: Subtitle path as shown by bazarr_item_subtitles.
            item_id: Sonarr series id or Radarr movie id.
            episode_id: Sonarr episode id (series only).
            forced: Forced subtitle.
            hearing_impaired: Hearing-impaired subtitle.
        """
        k = _kind(kind)
        if not k or item_id <= 0 or not path.strip():
            return "Give kind, item_id, language and path."
        form = {"language": language, "path": path, "forced": _tf(forced), "hi": _tf(hearing_impaired)}
        if k == "series":
            if episode_id <= 0:
                return "episode_id is required for series."
            form.update(seriesid=item_id, episodeid=episode_id)
            result = call("/episodes/subtitles", method="DELETE", data=form)
        else:
            form["radarrid"] = item_id
            result = call("/movies/subtitles", method="DELETE", data=form)
        if _http.is_error(result):
            return result
        return "🗑️ Subtitle deleted."

    @mcp.tool()
    def bazarr_history(kind: str = "series", limit: int = 20) -> str:
        """Recent subtitle activity (downloads, upgrades, syncs, deletions).

        Args:
            kind: "series" or "movies".
            limit: Max entries (default 20).
        """
        k = _kind(kind)
        if not k:
            return 'kind must be "series" or "movies".'
        actions = {0: "deleted", 1: "downloaded", 2: "manual", 3: "upgraded", 4: "uploaded",
                   5: "synced", 6: "translated", 7: "extracted"}
        data = call(f"/{'episodes' if k == 'series' else 'movies'}/history",
                    params={"start": 0, "length": max(1, min(limit, 200))})
        if _http.is_error(data):
            return data
        lines = []
        for h in data.get("data", []):
            title = (f"{h.get('seriesTitle', '?')} {h.get('episode_number', '')}" if k == "series"
                     else h.get("title", "?"))
            lang = (h.get("language") or {}).get("code2", "?")
            lines.append(f"• {h.get('timestamp', '?')} | {actions.get(h.get('action'), h.get('action'))} | "
                         f"{title} | {lang} | {h.get('provider') or '-'} | score {h.get('score') or '-'}")
        return "\n".join(lines) or "No history."

    @mcp.tool()
    def bazarr_providers(reset_throttled: bool = False) -> str:
        """Subtitle providers and whether they are throttled; optionally reset throttling.

        Args:
            reset_throttled: true to clear every provider's throttle (POST action=reset).
        """
        if reset_throttled:
            result = call("/providers", method="POST", data={"action": "reset"})
            if _http.is_error(result):
                return result
        data = call("/providers")
        if _http.is_error(data):
            return data
        lines = [f"• {p.get('name', '?')}: {p.get('status', '?')}"
                 f"{'' if p.get('retry') in (None, '-') else ' — retry ' + str(p.get('retry'))}"
                 for p in data.get("data", [])]
        prefix = "Throttling reset.\n" if reset_throttled else ""
        return prefix + ("\n".join(lines) or "No providers enabled.")

    @mcp.tool()
    def bazarr_jobs(status: str = "") -> str:
        """Bazarr job queue (subtitle searches/downloads in progress or finished).

        Args:
            status: Optional filter: pending, running, failed or completed.
        """
        params = {"status": status} if status in ("pending", "running", "failed", "completed") else None
        data = call("/system/jobs", params=params)
        if _http.is_error(data):
            return data
        lines = []
        for j in data.get("data", []):
            progress = ""
            if j.get("is_progress") and j.get("progress_max"):
                progress = f" {j.get('progress_value', 0)}/{j.get('progress_max')}"
            lines.append(f"• [{j.get('job_id')}] {j.get('job_name', '?')} — {j.get('status', '?')}{progress}"
                         f"{' — ' + j['progress_message'] if j.get('progress_message') else ''}")
        return "\n".join(lines) or "No jobs."

    @mcp.tool()
    def bazarr_tasks(run_task_id: str = "") -> str:
        """List Bazarr scheduled tasks, or run one now.

        Args:
            run_task_id: Task id to start immediately (e.g. wanted_search_missing_subtitles_series,
                wanted_search_missing_subtitles_movies, upgrade_subtitles, update_series,
                update_movies, series_full_scan_subtitles, movies_full_scan_subtitles).
                Leave empty to only list.
        """
        if run_task_id.strip():
            result = call("/system/tasks", method="POST", data={"taskid": run_task_id.strip()})
            if _http.is_error(result):
                return result
            return f"▶️ Task {run_task_id} started."
        data = call("/system/tasks")
        if _http.is_error(data):
            return data
        lines = [f"• {t.get('job_id')}: {t.get('name', '?')} — every {t.get('interval', '?')}, "
                 f"next {t.get('next_run_in', '?')}{' (running)' if t.get('job_running') else ''}"
                 for t in data.get("data", [])]
        return "\n".join(lines) or "No tasks."

    @mcp.tool()
    def bazarr_language_profiles() -> str:
        """Bazarr language profiles (which languages each profile downloads)."""
        data = call("/system/languages/profiles")
        if _http.is_error(data):
            return data
        lines = []
        for p in data if isinstance(data, list) else []:
            langs = ", ".join(
                f"{i.get('language', '?')}{' forced' if str(i.get('forced')) == 'True' else ''}"
                f"{' HI' if str(i.get('hi')) == 'True' else ''}" for i in p.get("items") or [])
            lines.append(f"• [{p.get('profileId')}] {p.get('name', '?')}: {langs}")
        return "\n".join(lines) or "No profiles."

    return {"bazarr_delete_subtitle"}
