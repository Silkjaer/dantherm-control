import importlib.machinery
import queue
import sys
import threading
import time
import types
import unittest
from pathlib import Path

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

from dantherm_gateway import Gateway  # noqa: E402


class _FakeGateway:
    def __init__(self, written):
        self.state = {}
        self.written_fan_pair = written

    def publish(self, key, value, **_kwargs):
        self.state[key] = value


class UnitFrostProtectionTests(unittest.TestCase):
    def test_a_lowered_supply_fan_is_the_units_frost_protection(self):
        update = Gateway.update_unit_frost_protection
        gw = _FakeGateway((70, 35))
        self.assertTrue(update(gw, (70, 16)))
        self.assertIs(gw.state["unit_frost_protection"], True)
        self.assertEqual(gw.state["unit_frost_supply_percent"], 16)
        self.assertFalse(update(gw, (70, 35)))
        self.assertIs(gw.state["unit_frost_protection"], False)
        self.assertIsNone(gw.state["unit_frost_supply_percent"])

    def test_anything_else_is_not_frost_protection(self):
        update = Gateway.update_unit_frost_protection
        gw = _FakeGateway((70, 35))
        self.assertFalse(update(gw, (40, 35)))
        self.assertFalse(update(gw, (70, 50)))
        self.assertFalse(update(gw, None))
        # Before the Pi has written a pair there is nothing to compare with.
        self.assertFalse(update(_FakeGateway(None), (70, 16)))


class FanWriteTests(unittest.TestCase):
    def gateway(self, readback):
        gateway = Gateway.__new__(Gateway)
        gateway.controller_hardware_queue = queue.SimpleQueue()
        gateway.state = {}
        gateway.written = []
        gateway.write_pair = lambda ser, extract, supply: gateway.written.append((extract, supply))
        gateway.read_fan_pair = lambda ser: readback
        gateway.publish = lambda key, value, **_kwargs: gateway.state.__setitem__(key, value)
        return gateway

    def write(self, gateway, pair):
        done = threading.Event()
        result = {}
        gateway.controller_hardware_queue.put(("fan_pair", pair, done, result, time.monotonic() + 5))
        gateway.process_controller_hardware(None)
        self.assertTrue(done.is_set())
        return result

    def test_the_units_frost_protection_is_not_a_failed_write(self):
        gateway = self.gateway((70, 16))
        result = self.write(gateway, (70, 35))
        self.assertNotIn("error", result)
        self.assertEqual(result["value"], (70, 16))
        self.assertEqual(gateway.written, [(70, 35)])
        self.assertIs(gateway.state["unit_frost_protection"], True)
        self.assertEqual(gateway.state["fan_supply_percent"], 16)

    def test_a_real_mismatch_is_still_an_error(self):
        gateway = self.gateway((40, 35))
        result = self.write(gateway, (70, 35))
        self.assertIn("fan readback mismatch", result["error"])
        self.assertIs(gateway.state["unit_frost_protection"], False)


if __name__ == "__main__":
    unittest.main()
