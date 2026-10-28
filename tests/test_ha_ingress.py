import http.client
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from controller_dashboard_server import ControllerDashboardHttpServer

INGRESS = "/api/hassio_ingress/abc123"


class FakeRuntime:
    def snapshot(self):
        return {"enabled": True, "active_master": "unknown"}


class HomeAssistantIngressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = ControllerDashboardHttpServer(
            "127.0.0.1", 0, {}, "Test", None,
            web_root=ROOT / "gateway/webui", history_path=Path(self.tmp.name) / "history.sqlite3",
            controller_runtime=FakeRuntime(),
        )
        self.server.auth.path = Path(self.tmp.name) / "auth.json"
        self.server.auth.session_path = Path(self.tmp.name) / "webui-sessions.json"
        self.server.auth.save("admin", "long-test-password", True)
        self.server.start()
        self.port = self.server.server.server_address[1]

    def tearDown(self):
        self.server.stop()
        self.tmp.cleanup()

    def get(self, path, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response, body

    def test_requests_through_the_ingress_proxy_are_logged_in_as_the_administrator(self):
        self.server.ingress_proxy = "127.0.0.1"
        page, _ = self.get("/", {"X-Ingress-Path": INGRESS})
        self.assertEqual(page.status, 200)
        cookie = page.getheader("Set-Cookie")
        self.assertIn("dantherm_session=", cookie)
        status, body = self.get("/api/auth/status", {"Cookie": cookie.split(";")[0], "X-Ingress-Path": INGRESS})
        self.assertEqual(status.status, 200)
        state = json.loads(body)
        self.assertTrue(state["authenticated"])
        self.assertEqual(state["username"], "admin")
        self.assertTrue(state["csrf"])

    def test_the_same_request_without_ingress_still_needs_a_login(self):
        self.server.ingress_proxy = "127.0.0.1"
        page, _ = self.get("/")
        self.assertEqual(page.status, 302)
        self.assertEqual(page.getheader("Location"), "/login")
        self.assertIsNone(page.getheader("Set-Cookie"))

    def test_ingress_headers_from_any_other_address_are_not_trusted(self):
        self.server.ingress_proxy = "172.30.32.2"
        page, _ = self.get("/", {"X-Ingress-Path": INGRESS})
        self.assertEqual(page.status, 302)
        self.assertEqual(page.getheader("Location"), f"{INGRESS}/login")
        self.assertIsNone(page.getheader("Set-Cookie"))

    def test_redirects_ignore_a_prefix_that_is_not_an_ingress_path(self):
        page, _ = self.get("/", {"X-Ingress-Path": "https://evil.example"})
        self.assertEqual(page.getheader("Location"), "/login")

    def test_built_pages_load_their_assets_relative_to_the_page(self):
        for name in ("index.html", "login.html"):
            html = (ROOT / "gateway/webui" / name).read_text()
            self.assertNotIn('src="/', html, name)
            self.assertNotIn('href="/', html, name)


if __name__ == "__main__":
    unittest.main()
