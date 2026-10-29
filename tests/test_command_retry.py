import importlib.machinery
import queue
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

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

from controller_core import ControllerEngine, ControllerState, HardwareAdapter
from dantherm_gateway import Gateway


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class CommandRetryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state = ControllerState(Path(directory.name) / "state.json")
        self.clock = Clock()
        clock_patch = patch("controller_core.time.time", self.clock)
        clock_patch.start()
        self.addCleanup(clock_patch.stop)

    def engine(self, **bindings):
        defaults = {
            "write_fan_pair": lambda extract, supply: None,
            "set_bypass": lambda value: None,
            "set_fireplace": lambda enabled: None,
            "set_afterheat_setpoint": lambda value: None,
        }
        defaults.update(bindings)
        return ControllerEngine(self.state, HardwareAdapter(**defaults))

    def test_a_wanted_command_is_tried_again_after_the_quick_retries(self):
        calls = []

        def fan_pair(extract, supply):
            calls.append((extract, supply))
            if len(calls) <= 3:
                raise OSError("bus unavailable")

        engine = self.engine(write_fan_pair=fan_pair)
        engine.retry_base_seconds = 0
        self.state.configure({"mode": "manual", "manual_level": 3})
        for _ in range(10):
            try:
                engine.apply()
            except OSError:
                pass
        self.assertEqual(len(calls), 3)
        self.clock.now += engine.retry_slow_seconds + 1
        engine.apply()
        self.assertEqual(len(calls), 4)
        self.assertEqual(engine.last_applied["fan_pair"], calls[-1])
        self.assertNotIn("fan_pair", engine._retry_at)

    def test_a_failed_write_leaves_the_unit_state_unknown(self):
        unit = {"bypass": "off"}

        def write(value):
            unit["bypass"] = value

        def write_then_lose_the_reply(value):
            unit["bypass"] = value
            raise RuntimeError("bypass readback mismatch: None")

        engine = self.engine()
        engine._call("bypass", "off", write, "off")
        with self.assertRaises(RuntimeError):
            engine._call("bypass", "on", write_then_lose_the_reply, "on")
        self.assertEqual(unit["bypass"], "on")
        engine._call("bypass", "off", write, "off")
        self.assertEqual(unit["bypass"], "off")
        self.assertNotIn("bypass", engine._uncertain)

    def test_an_unchanged_bypass_is_checked_again_every_minute(self):
        calls = []
        engine = self.engine(set_bypass=calls.append)
        engine.apply()
        engine.apply()
        self.assertEqual(len(calls), 1)
        self.clock.now += 61
        engine.apply()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])


class HardwareQueueTests(unittest.TestCase):
    def gateway(self):
        gateway = Gateway.__new__(Gateway)
        gateway.controller_hardware_queue = queue.SimpleQueue()
        gateway.written = []
        gateway.write_bypass_request = lambda ser, value: gateway.written.append(value) or value
        return gateway

    def test_a_command_whose_caller_timed_out_is_dropped(self):
        gateway = self.gateway()
        done = threading.Event()
        result = {}
        gateway.controller_hardware_queue.put(("bypass", "on", done, result, time.monotonic() - 1))
        gateway.process_controller_hardware(None)
        self.assertTrue(done.is_set())
        self.assertEqual(gateway.written, [])
        self.assertIn("error", result)

    def test_a_waiting_command_is_carried_out(self):
        gateway = self.gateway()
        caller = {}

        def call():
            caller["value"] = gateway.queue_controller_hardware("bypass", "off")

        thread = threading.Thread(target=call)
        thread.start()
        for _ in range(100):
            if not gateway.controller_hardware_queue.empty():
                break
            time.sleep(0.01)
        gateway.process_controller_hardware(None)
        thread.join(5)
        self.assertEqual(gateway.written, ["off"])
        self.assertEqual(caller["value"], "off")


if __name__ == "__main__":
    unittest.main()
