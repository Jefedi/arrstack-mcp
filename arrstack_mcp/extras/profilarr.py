"""Profilarr V2 tools.

Checked against Profilarr v2.3.1 (src/routes/api/v1/**, docs/api/v1/openapi.yaml):
* API base /api/v1 (that is the API version — this IS Profilarr V2). Auth: X-Api-Key
  (the PROFILARR_API_KEY env key of the container, or a key from Settings → Security).
* The API only exposes status (incl. per-arr sync state and per-database counts),
  databases (git repos) and jobs. Pushing profiles to Radarr/Sonarr and listing
  profiles / custom formats are UI-only, so they are not available here.
* POST /databases/{id}/sync only PULLS the git database, and only when auto_pull is on.
"""

from __future__ import annotations

import time

from . import _http


def register(mcp, server):
    settings = server.SETTINGS
    url = settings.get("PROFILARR_URL", "").rstrip("/")
    key = settings.get("PROFILARR_API_KEY", "")

    def call(path, method="GET", json=None):
        headers = {"X-Api-Key": key} if key else {}
        return _http.request(server, "Profilarr", url, f"/api/v1{path}", method=method, headers=headers, json=json)

    def _job_line(job: dict) -> str:
        result = job.get("result") or {}
        detail = result.get("output") or result.get("error") or ""
        return f"Job {job.get('id')} ({job.get('jobType', '?')}): {job.get('status', '?')}{' — ' + detail if detail else ''}"

    @mcp.tool()
    def profilarr_status() -> str:
        """Profilarr version, linked databases (profile/format counts, last pull) and the sync
        state of quality profiles, delay profiles and media management for each Radarr/Sonarr."""
        data = call("/status")
        if _http.is_error(data):
            return data
        lines = [f"Profilarr {data.get('version', '?')} — jobs active {(data.get('jobs') or {}).get('active', '?')}, "
                 f"queued {(data.get('jobs') or {}).get('queued', '?')}"]
        lines.append("Databases:")
        for db in data.get("databases", []):
            c = db.get("counts") or {}
            lines.append(f"• [{db.get('id')}] {db.get('name', '?')} — {c.get('qualityProfiles', '?')} profiles, "
                         f"{c.get('customFormats', '?')} custom formats, last pull {db.get('lastSyncedAt') or 'never'} "
                         f"({db.get('syncStrategy', '?')}){'' if db.get('enabled') else ' (disabled)'}")
        lines.append("Arr instances:")
        for arr in data.get("arrs", []):
            sync = arr.get("sync") or {}
            parts = []
            for name, label in (("qualityProfiles", "profiles"), ("delayProfiles", "delay"),
                                ("mediaManagement", "media mgmt")):
                s = sync.get(name) or {}
                parts.append(f"{label}: {s.get('status', '?')}"
                             f"{' (' + str(s.get('count')) + ')' if s.get('count') is not None else ''}")
            lines.append(f"• [{arr.get('id')}] {arr.get('name', '?')} ({arr.get('type', '?')}) — " + ", ".join(parts))
        return "\n".join(lines)

    @mcp.tool()
    def profilarr_pull_database(database_id: int) -> str:
        """Pull the latest commits of a Profilarr database (git repo). Does NOT push anything
        to Radarr/Sonarr. Only pulls if auto-pull is on for that database; otherwise the job
        only reports that updates are available.

        Args:
            database_id: Database id from profilarr_status.
        """
        if database_id <= 0:
            return "Invalid database_id."
        data = call(f"/databases/{database_id}/sync", method="POST")
        if _http.is_error(data):
            return data
        job_id = data.get("jobId")
        if not job_id:
            return f"Sync requested: {data}"
        for _ in range(10):
            time.sleep(1.5)
            job = call(f"/jobs/{job_id}")
            if isinstance(job, dict) and job.get("status") in ("success", "failed", "cancelled"):
                return _job_line(job)
        return f"Job {job_id} still running — check it with profilarr_job."

    @mcp.tool()
    def profilarr_job(job_id: int) -> str:
        """Status and output of a Profilarr job."""
        if job_id <= 0:
            return "Invalid job_id."
        job = call(f"/jobs/{job_id}")
        if _http.is_error(job):
            return job
        return _job_line(job)

    return set()
