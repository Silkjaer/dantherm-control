import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from controller_core import HardwareAdapter
from controller_dashboard_server import HEALTH_MAX_AGE_SECONDS, ControllerDashboardHttpServer
from controller_runtime import ControllerRuntime


class FakeRuntime:
    def __init__(self):
        self.last_tick_at = time.time()
        self.thread = None

    def snapshot(self):
        return {"enabled": True, "active_master": "unknown"}


class HealthEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = {"bus_loop_monotonic": time.monotonic(), "bus_traffic": False}
        self.runtime = FakeRuntime()
        self.server = ControllerDashboardHttpServer(
            "127.0.0.1", 0, self.state, "Test", None,
            web_root=ROOT / "gateway/webui", history_path=Path(self.tmp.name) / "history.sqlite3",
            controller_runtime=self.runtime,
        )
        self.server.auth.path = Path(self.tmp.name) / "auth.json"
        self.server.auth.session_path = Path(self.tmp.name) / "webui-sessions.json"
        self.server.auth.save("admin", "long-test-password", True)
        self.server.start()
        self.port = self.server.server.server_address[1]

    def tearDown(self):
        self.server.stop()
        self.tmp.cleanup()

    def get(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", "/healthz")
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
        return response.status, body

    def test_running_loops_are_healthy_without_a_login_even_on_a_silent_bus(self):
        status, body = self.get()
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertIs(body["bus_traffic"], False)

    def test_a_stuck_bus_loop_is_unhealthy(self):
        self.state["bus_loop_monotonic"] = time.monotonic() - HEALTH_MAX_AGE_SECONDS - 1
        status, body = self.get()
        self.assertEqual(status, 503)
        self.assertFalse(body["ok"])

    def test_a_controller_that_stopped_ticking_is_unhealthy(self):
        self.runtime.last_tick_at = time.time() - HEALTH_MAX_AGE_SECONDS - 1
        self.assertEqual(self.get()[0], 503)

    def test_loops_that_never_started_are_unhealthy_after_start_up(self):
        del self.state["bus_loop_monotonic"]
        self.assertEqual(self.get()[0], 200)
        self.server.started_monotonic -= 3600
        self.assertEqual(self.get()[0], 503)


class ControllerThreadTests(unittest.TestCase):
    def test_a_failing_tick_does_not_end_the_controller_thread(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        runtime = ControllerRuntime(
            gateway_state={}, hardware=HardwareAdapter(),
            state_path=Path(temp.name) / "controller.json", tick_seconds=1,
        )
        calls = []
        ticked_twice = threading.Event()

        def tick():
            calls.append(1)
            if len(calls) >= 2:
                ticked_twice.set()
            raise RuntimeError("boom")

        with patch.object(runtime, "tick", tick), self.assertLogs("passivelink-controller", level="ERROR"):
            runtime.start()
            self.assertTrue(ticked_twice.wait(5))
            self.assertTrue(runtime.thread.is_alive())
            runtime.stop()


if __name__ == "__main__":
    unittest.main()
