"""Gluetun control server tools (VPN in front of qBittorrent and the *arr apps).

Checked against Gluetun v3.41.3 (internal/server/*):
* Auth: X-API-Key header only — the ?api_key= query passes auth but then breaks
  routing (handlers compare RequestURI including the query string).
* GET /v1/version, /v1/vpn/status, /v1/publicip/ip, /v1/portforward, /v1/dns/status
* PUT /v1/vpn/status {"status": "running"|"stopped"}
VPN settings routes are left out on purpose: they can return provider credentials.
"""

from __future__ import annotations

import time

from . import _http


def register(mcp, server):
    settings = server.SETTINGS
    url = settings.get("GLUETUN_URL", "").rstrip("/")
    key = settings.get("GLUETUN_API_KEY", "")

    def call(path, method="GET", json=None):
        headers = {"X-API-Key": key} if key else {}
        return _http.request(server, "Gluetun", url, path, method=method, headers=headers, json=json)

    @mcp.tool()
    def gluetun_status() -> str:
        """VPN tunnel state, public exit IP/location, forwarded port(s) and DNS state of Gluetun."""
        vpn = call("/v1/vpn/status")
        if _http.is_error(vpn):
            return vpn
        lines = [f"VPN: {vpn.get('status', '?')}"]
        version = call("/v1/version")
        if isinstance(version, dict):
            lines[0] += f" (Gluetun {version.get('version', '?')})"
        ip = call("/v1/publicip/ip")
        if isinstance(ip, dict):
            where = ", ".join(x for x in (ip.get("city"), ip.get("region"), ip.get("country")) if x)
            lines.append(f"Public IP: {ip.get('public_ip') or '?'}{' — ' + where if where else ''}"
                         f"{' (' + ip['organization'] + ')' if ip.get('organization') else ''}")
        else:
            lines.append(f"Public IP: {ip}")
        pf = call("/v1/portforward")
        if isinstance(pf, dict):
            ports = pf.get("ports") or ([pf["port"]] if pf.get("port") else [])
            lines.append(f"Forwarded port(s): {', '.join(map(str, ports)) or 'none'}")
        dns = call("/v1/dns/status")
        if isinstance(dns, dict):
            lines.append(f"DNS: {dns.get('status', '?')}")
        return "\n".join(lines)

    @mcp.tool()
    def gluetun_restart_vpn() -> str:
        """Reconnect the VPN tunnel (stop, then start). Interrupts every download and the
        *arr apps' indexer access for a few seconds; the forwarded port may change.
        Ask the user before using it."""
        stop = call("/v1/vpn/status", method="PUT", json={"status": "stopped"})
        if _http.is_error(stop):
            return stop
        time.sleep(2)
        start = call("/v1/vpn/status", method="PUT", json={"status": "running"})
        if _http.is_error(start):
            return f"⚠️ VPN stopped but restart failed: {start}"
        return f"🔁 VPN restarting ({(start or {}).get('outcome', 'ok')}). Check gluetun_status in a few seconds."

    return set()
