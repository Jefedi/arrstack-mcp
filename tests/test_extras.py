"""Tests for the fork's extra tools (arrstack_mcp/extras).

Each extras module is registered on a fake MCP with a fake ``server`` namespace,
so the tests don't depend on the process environment.
"""

import logging
import types
import unittest
from unittest import mock

import httpx

from arrstack_mcp import server as real_server
from arrstack_mcp.extras import (_http, arr_extra, bazarr, crossseed, dispatcharr, gluetun,
                                 jellystat, media_extra, profilarr, wizarr)


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, *args, **kwargs):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


def fake_server(settings=None, **helpers):
    ns = types.SimpleNamespace(
        SETTINGS=settings or {},
        logger=logging.getLogger("test-extras"),
        _http_error=real_server._http_error,
        _decode_json=real_server._decode_json,
        _tag_labels=real_server._tag_labels,
        _action_ok=real_server._action_ok,
        _format_size=real_server._format_size,
    )
    for name, value in helpers.items():
        setattr(ns, name, value)
    return ns


def register(module, settings=None, **helpers):
    mcp = FakeMCP()
    destructive = module.register(mcp, fake_server(settings, **helpers))
    return mcp.tools, destructive


def response(status=200, json_body=None, text=None, method="GET", url="http://x/"):
    req = httpx.Request(method, url)
    if json_body is not None:
        return httpx.Response(status, json=json_body, request=req)
    return httpx.Response(status, text=text or "", request=req)


class HttpHelperTests(unittest.TestCase):
    def test_not_configured(self):
        result = _http.request(fake_server(), "Bazarr", "", "/api/x")
        self.assertTrue(_http.is_error(result))

    def test_http_error_is_error(self):
        with mock.patch("httpx.request", return_value=response(500, text="boom")):
            result = _http.request(fake_server(), "Bazarr", "http://b", "/x")
        self.assertTrue(_http.is_error(result))
        self.assertIn("HTTP 500", result)

    def test_json_and_text(self):
        with mock.patch("httpx.request", return_value=response(json_body={"a": 1})):
            self.assertEqual(_http.request(fake_server(), "S", "http://s", "/x"), {"a": 1})
        with mock.patch("httpx.request", return_value=response(text="OK")):
            self.assertEqual(_http.request(fake_server(), "S", "http://s", "/x", expect_json=False), "OK")


class ArrExtraTests(unittest.TestCase):
    def setUp(self):
        self.sonarr = mock.Mock(return_value={"id": 7, "status": "queued"})
        self.radarr = mock.Mock(return_value={"id": 8, "status": "queued"})
        self.tools, self.destructive = register(arr_extra, _sonarr=self.sonarr, _radarr=self.radarr)

    def test_destructive_names(self):
        self.assertEqual(self.destructive, {"sonarr_delete_series", "radarr_delete_movie"})
        for name in self.destructive:
            self.assertIn(name, self.tools)

    def test_unknown_command_rejected(self):
        self.assertIn("Unknown command", self.tools["sonarr_command"]("DeleteEverything"))
        self.sonarr.assert_not_called()

    def test_command_body(self):
        self.tools["sonarr_command"]("RefreshSeries", 12)
        self.sonarr.assert_called_with("/command", method="POST", json={"name": "RefreshSeries", "seriesIds": [12]})
        self.tools["radarr_command"]("RescanMovie", 3)
        self.radarr.assert_called_with("/command", method="POST", json={"name": "RescanMovie", "movieId": 3})

    def test_command_needs_id(self):
        self.assertIn("needs", self.tools["sonarr_command"]("SeriesSearch", 0))

    def test_delete_refuses_keep_tag(self):
        def sonarr(path, **kwargs):
            if path == "/tag":
                return [{"id": 1, "label": "mediacleaner-keep"}]
            if path == "/series/5":
                return {"id": 5, "title": "Show", "tags": [1]}
            raise AssertionError(f"unexpected call {path} {kwargs}")
        tools, _ = register(arr_extra, _sonarr=sonarr, _radarr=self.radarr)
        result = tools["sonarr_delete_series"](5)
        self.assertIn("keep", result.lower())


class MediaExtraTests(unittest.TestCase):
    def setUp(self):
        self.seerr = mock.Mock(return_value={"id": 3, "status": 1})
        self.qbt = mock.Mock(return_value="")
        self.tools, self.destructive = register(media_extra, _seerr=self.seerr, _jellyfin=mock.Mock(),
                                                _qbt=self.qbt)

    def test_request_4k_sends_is4k(self):
        self.tools["seerr_request_4k"](603, "tv", "1,2")
        self.seerr.assert_called_with("/request", method="POST",
                                      json={"mediaType": "tv", "mediaId": 603, "is4k": True, "seasons": [1, 2]})

    def test_moderate_validates_decision(self):
        self.assertIn("decision", self.tools["seerr_moderate_request"](1, "delete"))
        self.seerr.assert_not_called()

    def test_qbt_refuses_all(self):
        for name in ("qbt_recheck", "qbt_reannounce"):
            self.assertIn("not 'all'", self.tools[name]("all"))
        self.assertIn("not 'all'", self.tools["qbt_set_category"]("all", "tv"))
        self.qbt.assert_not_called()

    def test_qbt_recheck_ok(self):
        self.assertIn("Recheck", self.tools["qbt_recheck"]("abc"))
        self.qbt.assert_called_with("/torrents/recheck", method="POST", data={"hashes": "abc"})


class HttpServiceTests(unittest.TestCase):
    """Services that talk HTTP directly: auth header, not-configured and destructive sets."""

    CASES = (
        (bazarr, "BAZARR", "X-API-KEY", "bazarr_status", {"bazarr_delete_subtitle"}),
        (crossseed, "CROSSSEED", "X-Api-Key", "crossseed_status", set()),
        (gluetun, "GLUETUN", "X-API-Key", "gluetun_status", set()),
        (jellystat, "JELLYSTAT", "x-api-token", "jellystat_users", set()),
        (wizarr, "WIZARR", "X-API-Key", "wizarr_status", {"wizarr_delete_user", "wizarr_delete_invitation"}),
        (dispatcharr, "DISPATCHARR", "X-API-Key", "dispatcharr_plugins", set()),
        (profilarr, "PROFILARR", "X-Api-Key", "profilarr_status", set()),
    )

    def test_auth_header_sent(self):
        for module, prefix, header, tool, _ in self.CASES:
            with self.subTest(module=module.__name__):
                tools, _ = register(module, {f"{prefix}_URL": "http://svc", f"{prefix}_API_KEY": "k3y"})
                with mock.patch("httpx.request", return_value=response(json_body={})) as req:
                    tools[tool]()
                self.assertTrue(req.called)
                self.assertEqual(req.call_args.kwargs["headers"].get(header), "k3y")
                self.assertTrue(req.call_args.args[1].startswith("http://svc/"))

    def test_not_configured(self):
        for module, _, _, tool, _ in self.CASES:
            with self.subTest(module=module.__name__):
                tools, _ = register(module, {})
                with mock.patch("httpx.request") as req:
                    result = tools[tool]()
                req.assert_not_called()
                self.assertIn("not configured", result)

    def test_destructive_sets(self):
        for module, _, _, _, expected in self.CASES:
            with self.subTest(module=module.__name__):
                tools, destructive = register(module, {})
                self.assertEqual(set(destructive), expected)
                for name in tools:
                    if "delete" in name:
                        self.assertIn(name, destructive)


class ValidationTests(unittest.TestCase):
    def test_crossseed_hash_validation(self):
        tools, _ = register(crossseed, {"CROSSSEED_URL": "http://c", "CROSSSEED_API_KEY": "k"})
        with mock.patch("httpx.request") as req:
            self.assertNotIn("✅", tools["crossseed_search_torrent"](info_hash="nothex"))
            self.assertNotIn("✅", tools["crossseed_search_torrent"](info_hash="a" * 40, path="/x"))
        req.assert_not_called()

    def test_crossseed_unknown_job(self):
        tools, _ = register(crossseed, {"CROSSSEED_URL": "http://c", "CROSSSEED_API_KEY": "k"})
        with mock.patch("httpx.request") as req:
            tools["crossseed_run_job"]("format-disk")
        req.assert_not_called()

    def test_wizarr_link_expiry_validation(self):
        tools, _ = register(wizarr, {"WIZARR_URL": "http://w", "WIZARR_API_KEY": "k"})
        with mock.patch("httpx.request") as req:
            self.assertIn("1, 7 or 30", tools["wizarr_create_invitation"]("1", expires_in_days=3))
        req.assert_not_called()

    def test_wizarr_public_link(self):
        tools, _ = register(wizarr, {"WIZARR_URL": "http://10.0.0.1:5690", "WIZARR_API_KEY": "k",
                                     "WIZARR_PUBLIC_URL": "https://wizarr.example.com"})
        body = {"invitation": {"code": "ABC", "url": "/j/ABC", "unlimited": False, "duration": "unlimited"}}
        with mock.patch("httpx.request", return_value=response(json_body=body)) as req:
            result = tools["wizarr_create_invitation"]("1")
        self.assertIn("https://wizarr.example.com/j/ABC", result)
        self.assertEqual(req.call_args.kwargs["json"]["server_ids"], [1])


class RegistrationTests(unittest.TestCase):
    def test_extra_destructive_tools_registered_upstream(self):
        for name in ("sonarr_delete_series", "radarr_delete_movie", "bazarr_delete_subtitle",
                     "wizarr_delete_user", "wizarr_delete_invitation", "seerr_delete_request"):
            self.assertIn(name, real_server.DESTRUCTIVE_TOOLS)


class QbtResumeGuardTests(unittest.TestCase):
    def test_resume_all_refused(self):
        with mock.patch.object(real_server, "_qbt_action") as action:
            for value in ("all", "ALL", "abc|all"):
                self.assertIn("not allowed", real_server.qbt_resume(value))
        action.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class EnvNewlineTests(unittest.TestCase):
    def test_trailing_crlf_is_removed(self):
        from arrstack_mcp import config
        loaded = config.load({"SONARR_API_KEY": "abc123\r\n", "QBT_PASS": " p w \n"})
        self.assertEqual(loaded.values["SONARR_API_KEY"], "abc123")
        self.assertEqual(loaded.values["QBT_PASS"], " p w ")
