"""Small HTTP helper shared by the extra services (same error style as upstream)."""

from __future__ import annotations

import httpx


def request(server, service: str, base_url: str, path: str, *, method: str = "GET",
            headers: dict | None = None, json=None, params=None, data=None,
            timeout: float = 30, expect_json: bool = True):
    """Call ``base_url + path``.

    Returns the decoded JSON (``{}`` for an empty body), the response text when
    ``expect_json`` is false, or a readable error string on any failure.
    A ``str`` result therefore means "error" only when ``expect_json`` is true.
    """
    if not base_url:
        return f"{service} is not configured. Set its URL in the server settings."
    server.logger.info("%s %s %s", service.lower(), method, path)
    try:
        r = httpx.request(method, f"{base_url.rstrip('/')}{path}", headers=headers or {},
                          json=json, params=params, data=data, timeout=timeout)
        r.raise_for_status()
    except (httpx.HTTPStatusError, httpx.RequestError) as error:
        return server._http_error(service, error)
    if not expect_json:
        return r.text
    return server._decode_json(service, r)


def is_error(result) -> bool:
    """True for the error strings produced by ``request`` / ``server._http_error``."""
    return isinstance(result, str) and (
        " request failed: " in result or " request error: " in result or " is not configured" in result
        or "non-JSON response" in result)
