import importlib.machinery
import sys
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

from dantherm_gateway import Gateway, crc16

MINUS_FIVE = 65036  # -5.00 C as signed hundredths


class FakeMqtt:
    def publish(self, topic, payload, retain=False):
        pass


def make_gateway():
    gateway = Gateway.__new__(Gateway)
    gateway.device_id = "dantherm_hch5"
    gateway.prefix = "dantherm/hch5"
    gateway.client = FakeMqtt()
    gateway.fireplace_gateway_active = False
    gateway.state = {}
    gateway.retain = True
    gateway.mqtt_enabled = False
    return gateway


class SignedTemperatureTests(unittest.TestCase):
    def test_active_poll_reads_frost_as_minus_and_faults_as_missing(self):
        gateway = make_gateway()
        blocks = {(1, 0): [MINUS_FIVE, 1850, 2100, 0x7FFF]}
        gateway.read_fan_pair = lambda ser: None
        gateway.read_register_block = lambda ser, slave, start, count, function=3: blocks.get((slave, start))
        gateway._mirror_active_block = lambda *args: None
        gateway.poll_master_blocks(None)
        self.assertEqual(gateway.state["outdoor_temp"], -5.0)
        self.assertEqual(gateway.state["outdoor_temperature"], -5.0)
        self.assertEqual(gateway.state["supply_temp"], 18.5)
        self.assertIsNone(gateway.state.get("exhaust_temp"))

    def test_passive_fc04_frame_reads_frost_as_minus(self):
        gateway = make_gateway()
        gateway.last_bus_frame = 0.0
        values = [MINUS_FIVE, 1850, 2100, 0x8000]
        body = bytes([1, 4, 8]) + b"".join(value.to_bytes(2, "big") for value in values)
        gateway.decode(body + crc16(body).to_bytes(2, "little"))
        self.assertEqual(gateway.state["outdoor_temp"], -5.0)
        self.assertIsNone(gateway.state.get("exhaust_temperature"))

    def test_afterheat_block_sends_frost_as_a_register_word(self):
        gateway = make_gateway()
        gateway.state.update({"outdoor_temp": -5.0, "supply_temp": 18.5, "extract_temp": 21.0, "exhaust_temp": 1.25})
        gateway.read_register_block = lambda ser, slave, start, count, function=3: [0, 0, 0, 0, 2150]
        words = gateway._afterheat_temperature_words(None)
        self.assertEqual(words, [MINUS_FIVE, 1850, 2100, 125, 2150])
        Gateway.write_multiple_frame(0x40, 180, words)


if __name__ == "__main__":
    unittest.main()
