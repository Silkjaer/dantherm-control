import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from hac1_presence import Hac1Presence

try:
    DEPENDENCIES_AVAILABLE = importlib.util.find_spec("paho.mqtt.client") is not None
except ModuleNotFoundError:
    DEPENDENCIES_AVAILABLE = False
if DEPENDENCIES_AVAILABLE:
    from dantherm_gateway import Gateway


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Hac1PresenceTests(unittest.TestCase):
    def test_unanswered_reads_mark_hac1_absent_while_the_unit_answers(self):
        presence = Hac1Presence(Clock())
        for _ in range(Hac1Presence.MISSES_TO_ABSENT - 1):
            presence.missed(unit_answering=True)
        self.assertEqual(presence.state, Hac1Presence.UNKNOWN)
        presence.missed(unit_answering=True)
        self.assertTrue(presence.absent)

    def test_a_dead_bus_is_not_a_missing_hac1(self):
        presence = Hac1Presence(Clock())
        for _ in range(10):
            presence.missed(unit_answering=False)
        self.assertEqual(presence.state, Hac1Presence.UNKNOWN)

    def test_a_hac1_that_answered_once_is_never_dropped_by_missed_reads(self):
        presence = Hac1Presence(Clock())
        presence.seen()
        for _ in range(10):
            presence.missed(unit_answering=True)
        self.assertEqual(presence.state, Hac1Presence.PRESENT)

    def test_hcp4_register_146_decides_directly(self):
        presence = Hac1Presence(Clock())
        presence.reported(False)
        self.assertTrue(presence.absent)
        presence.reported(True)
        self.assertEqual(presence.state, Hac1Presence.PRESENT)

    def test_absent_hac1_is_probed_once_per_interval_and_found_again(self):
        clock = Clock()
        presence = Hac1Presence(clock)
        presence.reported(False)
        self.assertFalse(presence.allow_read())
        clock.now += Hac1Presence.PROBE_INTERVAL
        self.assertTrue(presence.allow_read())
        self.assertFalse(presence.allow_read())
        presence.seen()
        self.assertTrue(presence.allow_read())


class FakeController:
    def hardware_writes_allowed(self):
        return True


@unittest.skipUnless(DEPENDENCIES_AVAILABLE, "paho-mqtt is installed by the project installer/CI")
class GatewayWithoutHac1Tests(unittest.TestCase):
    def make_gateway(self):
        gateway = Gateway.__new__(Gateway)
        gateway.controller = FakeController()
        gateway.state = {}
        gateway.mqtt_enabled = False
        gateway.last_afterheat_temperature_refresh = 0.0
        return gateway

    def test_hac1_reads_stop_after_it_never_answers(self):
        gateway = self.make_gateway()
        calls = []

        def bus(_ser, slave, start, count, function=3):
            calls.append(slave)
            return [1] * count if slave == 1 else None

        with patch.object(Gateway, "_read_register_block", side_effect=bus):
            self.assertIsNotNone(gateway.read_register_block(object(), 1, 0, 4, function=4))
            for _ in range(Hac1Presence.MISSES_TO_ABSENT):
                self.assertIsNone(gateway.read_register_block(object(), 0x40, 200, 5))
            self.assertTrue(gateway.hac1_presence().absent)
            self.assertEqual(gateway.state["hac1_presence"], "absent")
            calls.clear()
            self.assertIsNone(gateway.read_register_block(object(), 0x40, 205, 5))
            self.assertIsNotNone(gateway.read_register_block(object(), 1, 4, 5, function=4))
        self.assertEqual(calls, [1])

    def test_hac1_writes_are_skipped_once_it_is_absent(self):
        gateway = self.make_gateway()
        gateway.hac1_presence().reported(False)
        with patch.object(Gateway, "_write_afterheat_block") as block:
            self.assertFalse(gateway.refresh_afterheat_temperature_block_if_due(object(), now=1e6))
            with self.assertRaisesRegex(RuntimeError, "HAC1 not installed"):
                gateway.write_afterheat_setpoint(object(), 20)
            block.assert_not_called()

    def test_controller_afterheat_is_a_no_op_without_hac1(self):
        gateway = self.make_gateway()
        gateway.hac1_presence().reported(False)
        with patch.object(Gateway, "queue_controller_hardware") as queue:
            self.assertIsNone(gateway.controller_afterheat_setpoint(20))
        queue.assert_not_called()

    def test_controller_afterheat_waits_until_hac1_has_answered(self):
        gateway = self.make_gateway()
        with patch.object(Gateway, "queue_controller_hardware", return_value=20) as queue:
            self.assertIsNone(gateway.controller_afterheat_setpoint(20))
            queue.assert_not_called()
            gateway.hac1_presence().seen()
            self.assertEqual(gateway.controller_afterheat_setpoint(20), 20)
        queue.assert_called_once_with("afterheat_setpoint", 20)

    def test_nothing_is_written_to_a_hac1_that_has_not_answered(self):
        gateway = self.make_gateway()
        with patch.object(Gateway, "_write_afterheat_block") as block, \
                patch.object(Gateway, "write_afterheat_temperature_block") as temperatures:
            self.assertFalse(gateway.refresh_afterheat_temperature_block_if_due(object(), now=1e6))
            with self.assertRaisesRegex(RuntimeError, "HAC1 not detected yet"):
                gateway.write_afterheat_setpoint(object(), 20)
            block.assert_not_called()
            temperatures.assert_not_called()

    def test_failed_refresh_is_an_error_only_once_hac1_has_answered(self):
        gateway = self.make_gateway()
        failure = RuntimeError("afterheat T5 source word unavailable")
        with patch.object(Gateway, "write_afterheat_temperature_block", side_effect=failure):
            with self.assertNoLogs("dantherm_gateway", level="ERROR"):
                self.assertFalse(gateway.refresh_afterheat_temperature_block_if_due(object(), now=1e6))
            gateway.hac1_presence().seen()
            with self.assertLogs("dantherm_gateway", level="ERROR"):
                self.assertFalse(gateway.refresh_afterheat_temperature_block_if_due(object(), now=2e6))

    def test_installations_with_hac1_keep_reading_it(self):
        gateway = self.make_gateway()
        with patch.object(Gateway, "_read_register_block", return_value=[0x3000, 0x1100, 0, 800, 0]):
            for _ in range(5):
                self.assertIsNotNone(gateway.read_register_block(object(), 0x40, 200, 5))
        self.assertEqual(gateway.hac1_presence().state, Hac1Presence.PRESENT)


if __name__ == "__main__":
    unittest.main()
