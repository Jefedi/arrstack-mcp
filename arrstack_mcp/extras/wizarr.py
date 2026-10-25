"""Wizarr tools (Jellyfin invitations and users).

Checked against Wizarr v2026.10.1 (app/blueprints/api/api_routes.py):
* Auth: X-API-Key header only (created in Settings → General → API Keys).
* POST /api/invitations: `unlimited` means a REUSABLE code (default true), not an
  unlimited account; account lifetime is `duration` (days, as a string);
  `expires_in_days` (link lifetime) only accepts 1, 7 or 30.
* The invite `url` is relative (/j/<code>); WIZARR_PUBLIC_URL turns it into a full link.
* POST /api/users/<id>/disable deletes the user when the server can't disable it,
  so that endpoint is not exposed.
"""

from __future__ import annotations

from . import _http


def register(mcp, server):
    settings = server.SETTINGS
    url = settings.get("WIZARR_URL", "").rstrip("/")
    key = settings.get("WIZARR_API_KEY", "")
    public = (settings.get("WIZARR_PUBLIC_URL", "") or url).rstrip("/")

    def call(path, method="GET", json=None, params=None):
        headers = {"X-API-Key": key} if key else {}
        return _http.request(server, "Wizarr", url, f"/api{path}", method=method, headers=headers,
                             json=json, params=params, timeout=60)

    @mcp.tool()
    def wizarr_status() -> str:
        """Wizarr version and counters (users, pending / expired invitations)."""
        data = call("/status")
        if _http.is_error(data):
            return data
        version = call("/version")
        v = version.get("version", "?") if isinstance(version, dict) else "?"
        return (f"Wizarr {v}: {data.get('users', '?')} users, {data.get('invites', '?')} invitations "
                f"({data.get('pending', '?')} pending, {data.get('expired', '?')} expired).")

    @mcp.tool()
    def wizarr_servers_and_libraries() -> str:
        """Media servers and libraries known to Wizarr (their ids are needed to create invitations)."""
        servers = call("/servers")
        if _http.is_error(servers):
            return servers
        libs = call("/libraries")
        lines = ["Servers:"] + [f"• [{s.get('id')}] {s.get('name', '?')} ({s.get('server_type', '?')})"
                                f"{' ✅' if s.get('verified') else ' ⚠️ not verified'}"
                                for s in servers.get("servers", [])]
        if isinstance(libs, dict):
            lines.append("Libraries:")
            lines += [f"• [{l.get('id')}] {l.get('name', '?')} — server {l.get('server_name', '?')}"
                      f"{'' if l.get('enabled') else ' (disabled)'}" for l in libs.get("libraries", [])]
        return "\n".join(lines)

    @mcp.tool()
    def wizarr_users(username: str = "") -> str:
        """Users created through Wizarr, with server and expiry date.

        Args:
            username: Optional exact user name filter.
        """
        data = call("/users", params={"username": username} if username.strip() else None)
        if _http.is_error(data):
            return data
        lines = [f"• [{u.get('id')}] {u.get('username', '?')} ({u.get('email') or 'no email'}) — "
                 f"{u.get('server', '?')}, expires {u.get('expires') or 'never'}" for u in data.get("users", [])]
        return "\n".join(lines) or "No users."

    @mcp.tool()
    def wizarr_invitations() -> str:
        """List invitations with their link, status and settings."""
        data = call("/invitations")
        if _http.is_error(data):
            return data
        lines = []
        for i in data.get("invitations", []):
            link = f"{public}{i.get('url')}" if (i.get("url") or "").startswith("/") else i.get("url", "?")
            lines.append(f"• [{i.get('id')}] {i.get('code', '?')} — {i.get('status', '?')} | link {link} | "
                         f"account duration {i.get('duration', '?')} | "
                         f"{'reusable' if i.get('unlimited') else 'single use'} | "
                         f"expires {i.get('expires') or 'never'}"
                         f"{' | used by ' + str(i.get('used_by')) if i.get('used_by') else ''}")
        return "\n".join(lines) or "No invitations."

    @mcp.tool()
    def wizarr_create_invitation(server_ids: str = "", expires_in_days: int = 7, account_days: int = 0,
                                 reusable: bool = False, library_ids: str = "",
                                 allow_live_tv: bool = False, allow_downloads: bool = False) -> str:
        """Create a Jellyfin invitation link.

        Args:
            server_ids: Comma-separated Wizarr server ids (see wizarr_servers_and_libraries).
                Leave empty to get the list back.
            expires_in_days: When the LINK expires: 1, 7 or 30 (0 = never).
            account_days: How long the created ACCOUNT lasts in days (0 = no expiry).
            reusable: true lets several people use the same link (Wizarr's "unlimited").
            library_ids: Optional comma-separated Wizarr library ids (empty = all enabled libraries).
            allow_live_tv: Give Live TV access.
            allow_downloads: Allow downloads.
        """
        try:
            servers = [int(x) for x in server_ids.split(",") if x.strip()]
            libraries = [int(x) for x in library_ids.split(",") if x.strip()]
        except ValueError:
            return "server_ids and library_ids must be comma-separated numbers."
        if expires_in_days not in (0, 1, 7, 30):
            return "expires_in_days must be 0 (never), 1, 7 or 30."
        body: dict = {"server_ids": servers, "unlimited": reusable,
                      "duration": str(account_days) if account_days > 0 else "unlimited",
                      "allow_live_tv": allow_live_tv, "allow_downloads": allow_downloads}
        if expires_in_days:
            body["expires_in_days"] = expires_in_days
        if libraries:
            body["library_ids"] = libraries
        data = call("/invitations", method="POST", json=body)
        if _http.is_error(data):
            return data
        inv = data.get("invitation", {})
        link = f"{public}{inv.get('url')}" if (inv.get("url") or "").startswith("/") else inv.get("url", "?")
        return (f"✅ Invitation {inv.get('code', '?')} created: {link}\n"
                f"Link expires {inv.get('expires') or 'never'}; account duration {inv.get('duration', '?')}; "
                f"{'reusable' if inv.get('unlimited') else 'single use'}.")

    @mcp.tool()
    def wizarr_delete_invitation(invitation_id: int) -> str:
        """Delete an invitation (the link stops working; existing users are untouched)."""
        if invitation_id <= 0:
            return "Invalid invitation_id."
        data = call(f"/invitations/{invitation_id}", method="DELETE")
        if _http.is_error(data):
            return data
        return f"🗑️ {data.get('message', 'Invitation deleted.')}"

    @mcp.tool()
    def wizarr_extend_user(user_id: int, days: int = 30) -> str:
        """Push back a user's expiry date by N days (Wizarr user id from wizarr_users)."""
        if user_id <= 0 or days <= 0:
            return "Give a positive user_id and days."
        data = call(f"/users/{user_id}/extend", method="POST", json={"days": days})
        if _http.is_error(data):
            return data
        return f"✅ {data.get('message', 'Extended')} — new expiry {data.get('new_expiry', '?')}."

    @mcp.tool()
    def wizarr_delete_user(user_id: int) -> str:
        """Delete a user from Jellyfin AND Wizarr. DESTRUCTIVE (watch history on the server is lost)."""
        if user_id <= 0:
            return "Invalid user_id."
        data = call(f"/users/{user_id}", method="DELETE")
        if _http.is_error(data):
            return data
        return f"🗑️ {data.get('message', 'User deleted.')}"

    return {"wizarr_delete_user", "wizarr_delete_invitation"}
