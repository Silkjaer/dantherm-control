import importlib.machinery
import sys
import time
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "gateway"))

if "paho.mqtt.client" not in sys.modules:
    paho = types.ModuleType("paho")
    mqtt_package = types.ModuleType("paho.mqtt")
    mqtt_client = types.ModuleType("paho.mqtt.client")
    mqtt_client.__spec__ = importlib.machinery.ModuleSpec("paho.mqtt.client", loader=None)
    paho.mqtt = mqtt_package
    mqtt_package.client = mqtt_client
    sys.modules.update({
        "paho": paho,
        "paho.mqtt": mqtt_package,
        "paho.mqtt.client": mqtt_client,
    })

from dantherm_controller_gateway import Gateway
from master_arbitration import MasterArbitrator, RtuFrameStream, crc16


def fc06(register, value):
    body = bytes([1, 6, register >> 8, register & 0xFF, value >> 8, value & 0xFF])
    return body + crc16(body).to_bytes(2, "little")


class TransportOpenTests(unittest.TestCase):
    def test_observation_window_runs_from_the_restart(self):
        arb = MasterArbitrator()
        t0 = arb.started_monotonic
        # A slow (TCP) connect: the port opens 8 s after the arbitrator was made.
        arb.restart_observation(now=t0 + 8)
        arb.evaluate(bus_healthy=True, now=t0 + 12)
        self.assertEqual(arb.master, arb.UNKNOWN)
        self.assertEqual(arb.reason, "startup_observation")
        arb.evaluate(bus_healthy=True, now=t0 + 18.1)
        self.assertEqual(arb.master, arb.PI)

    def test_restart_makes_pi_listen_again_and_drops_own_echo_context(self):
        arb = MasterArbitrator(startup_observation=3)
        t0 = arb.started_monotonic
        arb.evaluate(bus_healthy=True, now=t0 + 3.1)
        self.assertTrue(arb.writes_allowed())
        write = fc06(67, 43)
        arb.note_own_frame(write, now=t0 + 4.0)
        arb.restart_observation(now=t0 + 4.01)
        self.assertFalse(arb.writes_allowed())
        self.assertEqual(arb.master, arb.UNKNOWN)
        # The same frame on the new connection is not our echo.
        self.assertEqual(arb.observe_frame(write, now=t0 + 4.02), "foreign")

    def test_restart_keeps_recent_hcp4_activity(self):
        arb = MasterArbitrator(startup_observation=3, release_timeout=10)
        t0 = arb.started_monotonic
        arb.observe_frame(fc06(67, 43), now=t0 + 1)
        arb.restart_observation(now=t0 + 2)
        arb.evaluate(bus_healthy=True, now=t0 + 5.5)
        self.assertNotEqual(arb.master, arb.PI)

    def test_stream_reset_drops_a_partial_frame(self):
        stream = RtuFrameStream()
        first, second = fc06(67, 43), fc06(66, 55)
        self.assertEqual(stream.feed(first[:5]), [])
        stream.reset()
        self.assertEqual(stream.feed(first[5:] + second), [second])

    def test_transport_open_restarts_arbitration_and_active_read_gate(self):
        gateway = Gateway.__new__(Gateway)
        arb = MasterArbitrator()
        # Created long before the port opened: the window has already run out.
        arb.started_monotonic -= 60
        stream = RtuFrameStream()
        stream.feed(fc06(67, 43)[:5])
        gateway.controller = SimpleNamespace(master=arb, master_stream=stream)
        self.assertTrue(gateway._active_read_allowed())

        gateway.transport_opened()
        self.assertFalse(gateway._active_read_allowed())
        self.assertAlmostEqual(arb.started_monotonic, time.monotonic(), delta=1.0)
        self.assertEqual(stream.buffer, bytearray())


if __name__ == "__main__":
    unittest.main()
