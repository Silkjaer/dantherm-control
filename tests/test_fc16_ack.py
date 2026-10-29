import importlib.machinery
import itertools
import sys
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

from dantherm_gateway import Gateway, crc16

THERMOSTAT = [1, 22 * 256, 15, 0x17FE, 0xFF03]
SERIAL = type("Serial", (), {"flush": lambda self: None})()


def hac1_ack(frame: bytes) -> bytes:
    return frame[:6] + crc16(frame[:6]).to_bytes(2, "little")


def make_gateway():
    gateway = Gateway.__new__(Gateway)
    gateway.state = {}
    gateway.mqtt_enabled = False
    return gateway


def wire(gateway, reply):
    """Answer every write with the chunks ``reply(frame)`` returns."""
    writes = []
    chunks = []

    def serial_write(_ser, data, reason):
        writes.append(data)
        chunks.extend(reply(data))
        return len(data)

    gateway.wait_quiet = lambda *_args: True
    gateway.serial_write = serial_write
    gateway.serial_read = lambda *_args: chunks.pop(0) if chunks else b""
    return writes


def write_block(gateway, start=185, values=THERMOSTAT):
    # A fake clock keeps the 2 x 0.5 s wait for a missing ack instant.
    ticks = itertools.count()
    with patch("dantherm_gateway.time.monotonic", side_effect=lambda: 1000 + next(ticks) * 0.01):
        gateway._write_afterheat_block(SERIAL, start, values, "CONTROL_AFTERHEAT_THERMOSTAT")


class Fc16AckTests(unittest.TestCase):
    def test_echo_of_own_request_is_not_an_ack(self):
        # An adapter that echoes our TX returns our own frame, which starts
        # with the ack's six bytes and is longer than eight.
        for chunks in (lambda frame: [frame], lambda frame: [frame[:8], frame[8:]],
                       lambda frame: [frame[:5], frame[5:12], frame[12:]]):
            gateway = make_gateway()
            writes = wire(gateway, chunks)
            with self.assertRaisesRegex(RuntimeError, "missing FC16 acknowledgement for register 185"):
                write_block(gateway)
            self.assertEqual(len(writes), 2)

    def test_ack_after_echo_is_accepted(self):
        for chunks in (lambda frame: [frame + hac1_ack(frame)],
                       lambda frame: [frame, hac1_ack(frame)],
                       lambda frame: [frame[:10], frame[10:] + hac1_ack(frame)[:3], hac1_ack(frame)[3:]]):
            gateway = make_gateway()
            writes = wire(gateway, chunks)
            write_block(gateway)
            self.assertEqual(len(writes), 1)

    def test_damaged_ack_after_echo_is_still_accepted(self):
        for damage in (lambda ack: ack[:7] + b"\xff", lambda ack: ack[:7], lambda ack: b"\xc0" + ack[1:]):
            gateway = make_gateway()
            writes = wire(gateway, lambda frame: [frame, damage(hac1_ack(frame))])
            write_block(gateway)
            self.assertEqual(len(writes), 1)

    def test_ack_bytes_inside_our_own_payload_are_not_an_ack(self):
        # Register values that spell the block's own ack (40 10 00 B4 00 05
        # 4F 3D) or its fallback tail (00 B4 00 05 4F) in the echoed payload.
        for values in ([0x4010, 0x00B4, 0x0005, 0x4F3D, 0], [0x00B4, 0x0005, 0x4F00, 0, 0]):
            for chunks in (lambda frame: [frame], lambda frame: [frame[:15], frame[15:]]):
                gateway = make_gateway()
                writes = wire(gateway, chunks)
                with self.assertRaisesRegex(RuntimeError, "missing FC16 acknowledgement for register 180"):
                    write_block(gateway, 180, values)
                self.assertEqual(len(writes), 2)

    def test_header_with_a_wrong_crc_is_not_an_ack(self):
        gateway = make_gateway()
        writes = wire(gateway, lambda frame: [frame[:6] + b"\x00\x00"])
        with self.assertRaisesRegex(RuntimeError, "missing FC16 acknowledgement"):
            write_block(gateway)
        self.assertEqual(len(writes), 2)

    def test_ack_split_across_reads_is_accepted(self):
        for split in range(1, 8):
            gateway = make_gateway()
            writes = wire(gateway, lambda frame: [hac1_ack(frame)[:split], hac1_ack(frame)[split:]])
            write_block(gateway)
            self.assertEqual(len(writes), 1)

    def test_without_own_echo_holds_back_a_partial_echo(self):
        frame = Gateway.write_multiple_frame(0x40, 185, THERMOSTAT)
        ack = hac1_ack(frame)
        self.assertEqual(Gateway.without_own_echo(frame + ack, frame), ack)
        self.assertEqual(Gateway.without_own_echo(frame[:12], frame), b"")
        self.assertEqual(Gateway.without_own_echo(b"\x00" + frame[:6], frame), b"\x00" + frame[:6])
        self.assertEqual(Gateway.without_own_echo(ack, frame), ack)


if __name__ == "__main__":
    unittest.main()
