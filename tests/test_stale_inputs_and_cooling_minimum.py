import importlib.machinery
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

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
from controller_runtime import ControllerRuntime
from dantherm_gateway import Gateway
from sensor_freshness import CONTROL_INPUT_MAX_AGE_SECONDS, fresh_control_input


class FreeCoolingMinimumTests(unittest.TestCase):
    def make_engine(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        state = ControllerState(Path(temp.name) / "controller.json")
        return ControllerEngine(state, HardwareAdapter())

    def test_a_manual_bypass_and_cool_are_the_users_choice_in_the_cold(self):
        engine = self.make_engine()
        engine.config.configure({"bypass": "on", "mode": "manual", "manual_level": 3, "cooling_outdoor_min": 12})
        engine.update_measurements(outdoor=-5)
        self.assertEqual(engine.resolve()["effective_bypass"], "on")
        engine.config.configure({"bypass": "off", "mode": "local_auto", "cool_boost_minutes": 60})
        self.assertEqual(engine.resolve()["effective_bypass"], "on")

    def test_minimum_run_time_does_not_hold_free_cooling_below_the_lowest_outdoor_temperature(self):
        engine = self.make_engine()
        engine.config.configure({
            "mode": "local_auto", "cooling_enabled": True, "cooling_room_setpoint": 22,
            "cooling_outdoor_min": 12, "cooling_min_on_seconds": 3600,
        })
        engine.cooling_active = True
        engine.cooling_last_on_at = time.time() - 60
        engine.update_measurements(room=22.3, outdoor=11)
        result = engine.resolve()
        self.assertFalse(result["cooling_active"])
        self.assertEqual(result["cooling_state"], "outdoor_too_cold")
        self.assertEqual(result["effective_bypass"], "off")


class StaleInputTests(unittest.TestCase):
    def test_none_clears_a_measurement_and_left_out_ones_are_kept(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        engine = ControllerEngine(ControllerState(Path(temp.name) / "controller.json"), HardwareAdapter())
        engine.update_measurements(rh=50, co2=700, outdoor=16, room=23)
        engine.update_measurements(outdoor=None)
        self.assertIsNone(engine.measurements["outdoor"])
        self.assertEqual(engine.measurements["rh"], 50.0)

    def test_publish_stamps_an_unchanged_control_input(self):
        gateway = Gateway.__new__(Gateway)
        gateway.state = {}
        gateway.mqtt_enabled = False
        gateway.publish("outdoor_temp", 16.0)
        first = gateway.state["outdoor_temp_seen_monotonic"]
        gateway.publish("outdoor_temp", 16.0)
        self.assertGreaterEqual(gateway.state["outdoor_temp_seen_monotonic"], first)
        now = gateway.state["outdoor_temp_seen_monotonic"]
        self.assertEqual(fresh_control_input(gateway.state, "outdoor_temp", now=now + 1), 16.0)
        self.assertIsNone(fresh_control_input(
            gateway.state, "outdoor_temp", now=now + CONTROL_INPUT_MAX_AGE_SECONDS + 1
        ))

    def test_the_controller_forgets_inputs_that_stopped_arriving(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        old = time.monotonic() - CONTROL_INPUT_MAX_AGE_SECONDS - 5
        state = {
            "outdoor_temp": 16.0, "outdoor_temp_seen_monotonic": old,
            "humidity": 48.0, "humidity_seen_monotonic": old,
            "extract_temp": 22.0, "extract_temp_seen_monotonic": time.monotonic(),
        }
        runtime = ControllerRuntime(
            gateway_state=state, hardware=HardwareAdapter(),
            state_path=Path(temp.name) / "controller.json",
        )
        runtime.engine.update_measurements(outdoor=16, rh=48)
        runtime.refresh_measurements()
        self.assertIsNone(runtime.engine.measurements["outdoor"])
        self.assertIsNone(runtime.engine.measurements["rh"])
        self.assertEqual(runtime.engine.external["extract_temp"], 22.0)


if __name__ == "__main__":
    unittest.main()
