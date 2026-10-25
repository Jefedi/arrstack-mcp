"""Discovery fingerprints for the fork's extra services.

Only services with an unauthenticated identifying endpoint get a real probe:
* Bazarr      GET /api/system/ping   -> {"status": "OK"}           (bazarr/api/system/ping.py)
* cross-seed  GET /api/ping          -> "OK"                        (src/server.ts)
* Dispatcharr GET /api/core/version/ -> {"version", "timestamp"}    (apps/core/api_views.py)
* Profilarr   GET /api/v1/health     -> {"status", "timestamp"}     (src/routes/api/v1/health)
Jellystat, Wizarr and Gluetun have no reliable anonymous endpoint: never probed.
"""

from __future__ import annotations


def extra_fingerprints(_json) -> dict:
    def bazarr(client, base):
        data = _json(client.get(f"{base}/api/system/ping"))
        return isinstance(data, dict) and str(data.get("status", "")).upper() == "OK"

    def crossseed(client, base):
        response = client.get(f"{base}/api/ping")
        return response.status_code == 200 and response.text.strip() == "OK"

    def dispatcharr(client, base):
        data = _json(client.get(f"{base}/api/core/version/"))
        return isinstance(data, dict) and "version" in data and "timestamp" in data

    def profilarr(client, base):
        data = _json(client.get(f"{base}/api/v1/health"))
        return isinstance(data, dict) and data.get("status") in ("healthy", "degraded", "unhealthy") \
            and "timestamp" in data

    def never(client, base):
        return False

    return {"bazarr": bazarr, "crossseed": crossseed, "dispatcharr": dispatcharr, "profilarr": profilarr,
            "jellystat": never, "wizarr": never, "gluetun": never}
