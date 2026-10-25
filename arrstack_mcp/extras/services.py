"""Service registry entries for the fork's extra services.

Kept free of imports from ``config`` (it imports us) — the registry classes and
helpers are passed in by ``config.py``.
"""

from __future__ import annotations


def build_services(Service, Setting, _url, _api_key) -> dict:
    services = (
        Service(
            "bazarr", "Bazarr", "Subtitles", "bazarr_",
            (_url("BAZARR_URL", "Bazarr", 6767), _api_key("BAZARR_API_KEY", "Bazarr", "Settings → General → Security")),
            6767, ("bazarr",), "Settings → General → Security → API Key",
            group="Movies & TV",
        ),
        Service(
            "profilarr", "Profilarr", "Quality profiles sync (V2)", "profilarr_",
            (_url("PROFILARR_URL", "Profilarr", 6868),
             _api_key("PROFILARR_API_KEY", "Profilarr",
                      "the container's PROFILARR_API_KEY, or Settings → Security → API keys")),
            6868, ("profilarr",), "PROFILARR_API_KEY env var, or Settings → Security → API keys",
            group="Movies & TV",
        ),
        Service(
            "crossseed", "cross-seed", "Cross-seeding daemon", "crossseed_",
            (_url("CROSSSEED_URL", "cross-seed", 2468),
             _api_key("CROSSSEED_API_KEY", "cross-seed", "`cross-seed api-key` in the container")),
            2468, ("cross-seed", "crossseed"), "run `cross-seed api-key` in the container",
            aliases=("cross-seed",),
            group="Downloads",
        ),
        Service(
            "gluetun", "Gluetun", "VPN gateway", "gluetun_",
            (_url("GLUETUN_URL", "Gluetun", 8000, what="control server URL"),
             _api_key("GLUETUN_API_KEY", "Gluetun",
                      "an `apikey` role in /gluetun/auth/config.toml or HTTP_CONTROL_SERVER_AUTH_DEFAULT_ROLE",
                      need="recommended")),
            8000, ("gluetun",), "apikey role in the control-server auth config",
            group="Downloads",
        ),
        Service(
            "jellystat", "Jellystat", "Jellyfin statistics", "jellystat_",
            (_url("JELLYSTAT_URL", "Jellystat", 3000), _api_key("JELLYSTAT_API_KEY", "Jellystat", "Settings → API Key")),
            3000, ("jellystat",), "Settings → API Key",
            group="Media server",
        ),
        Service(
            "wizarr", "Wizarr", "Jellyfin invitations", "wizarr_",
            (_url("WIZARR_URL", "Wizarr", 5690),
             _api_key("WIZARR_API_KEY", "Wizarr", "Settings → General → API Keys"),
             Setting("WIZARR_PUBLIC_URL", "public_url",
                     "Public Wizarr address used to build full invitation links (defaults to `WIZARR_URL`)",
                     example="https://wizarr.example.com", url=True)),
            5690, ("wizarr",), "Settings → General → API Keys",
            group="Media server",
        ),
        Service(
            "dispatcharr", "Dispatcharr", "IPTV channels and EPG", "dispatcharr_",
            (_url("DISPATCHARR_URL", "Dispatcharr", 9191),
             _api_key("DISPATCHARR_API_KEY", "Dispatcharr", "user menu → API key (use an admin user)")),
            9191, ("dispatcharr",), "user menu → API key (admin user)",
            group="Media server",
        ),
    )
    return {service.key: service for service in services}
