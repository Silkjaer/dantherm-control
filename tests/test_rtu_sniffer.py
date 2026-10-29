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

from dantherm_gateway import Gateway, RtuSniffer, crc16


def with_crc(body: bytes) -> bytes:
    return body + crc16(body).to_bytes(2, "little")


def words(values) -> bytes:
    return b"".join(value.to_bytes(2, "big") for value in values)


# One of each frame kind seen on the HCH5/HAC1 bus.
READ_REQUEST = Gateway.read_frame(180, 5, slave=0x40)
READ_RESPONSE = with_crc(bytes([0x40, 3, 10]) + words([2126, 1717, 0x8000, 0x8000, 16]))
FC04_RESPONSE = with_crc(bytes([1, 4, 8]) + words([1415, 2094, 2077, 1465]))
FC06_WRITE = Gateway.write_frame(67, 43)
FC16_REQUEST = Gateway.write_multiple_frame(0x40, 180, [1415, 2094, 2077, 1465, 2340])
FC16_ACK = with_crc(bytes([0x40, 16, 0, 180, 0, 5]))
EXCEPTION = with_crc(bytes([0x40, 0x83, 2]))
FRAMES = [READ_REQUEST, READ_RESPONSE, FC04_RESPONSE, FC06_WRITE, FC16_REQUEST, FC16_ACK, EXCEPTION]


def sniffer(deduplicate_ms: int = 0) -> RtuSniffer:
    return RtuSniffer("unused", 19200, "E", deduplicate_ms)


def feed_chunks(target: RtuSniffer, *chunks: bytes) -> list[bytes]:
    frames = []
    for chunk in chunks:
        frames.extend(target.feed(chunk))
    return frames


class RtuSnifferTests(unittest.TestCase):
    def test_frame_split_at_every_point_is_reassembled(self):
        # A TCP adapter delivers arbitrary chunks, e.g. the first 5 bytes and
        # then the rest. The start of the frame must not be dropped meanwhile.
        for frame in FRAMES:
            for split in range(1, len(frame)):
                with self.subTest(frame=frame.hex(), split=split):
                    self.assertEqual(
                        feed_chunks(sniffer(), frame[:split], frame[split:]), [frame]
                    )

    def test_frame_fed_byte_by_byte_is_reassembled(self):
        stream = b"".join(FRAMES)
        self.assertEqual(
            feed_chunks(sniffer(), *(stream[i:i + 1] for i in range(len(stream)))), FRAMES
        )

    def test_concatenated_frames_split_at_every_point(self):
        stream = b"".join(FRAMES)
        for split in range(len(stream) + 1):
            with self.subTest(split=split):
                self.assertEqual(feed_chunks(sniffer(), stream[:split], stream[split:]), FRAMES)

    def test_fc16_request_and_ack_are_both_recognised(self):
        # HCP4 writes five registers to HAC1 (19 bytes), HAC1 answers with 8.
        self.assertEqual(len(FC16_REQUEST), 19)
        self.assertEqual(
            feed_chunks(sniffer(), FC16_REQUEST[:5], FC16_REQUEST[5:] + FC16_ACK[:3], FC16_ACK[3:]),
            [FC16_REQUEST, FC16_ACK],
        )

    def test_crc_error_is_skipped_and_the_next_frame_is_found(self):
        damaged = bytearray(READ_RESPONSE)
        damaged[5] ^= 0x01
        stream = bytes(damaged) + FC16_REQUEST + FC06_WRITE
        for split in range(len(stream) + 1):
            with self.subTest(split=split):
                self.assertEqual(
                    feed_chunks(sniffer(), stream[:split], stream[split:]),
                    [FC16_REQUEST, FC06_WRITE],
                )

    def test_noise_and_a_truncated_ack_before_a_frame_are_skipped(self):
        # HAC1's ack sometimes loses its last CRC byte; the line goes on with
        # the next transaction and the parser must get back in step.
        stream = b"\x00\x40\xff" + FC16_ACK[:7] + READ_REQUEST + READ_RESPONSE
        self.assertEqual(feed_chunks(sniffer(), stream[:9], stream[9:]), [READ_REQUEST, READ_RESPONSE])

    def test_buffer_holds_at_most_one_partial_frame(self):
        target = sniffer()
        self.assertEqual(feed_chunks(target, b"\x01\x02\x03" * 2000), [])
        self.assertLess(len(target.stream.buffer), 5)
        self.assertEqual(feed_chunks(target, FC16_REQUEST[:12]), [])
        self.assertEqual(bytes(target.stream.buffer), FC16_REQUEST[:12])
        self.assertEqual(feed_chunks(target, FC16_REQUEST[12:]), [FC16_REQUEST])
        self.assertEqual(len(target.stream.buffer), 0)

    def test_repeated_frame_inside_the_window_is_reported_once(self):
        self.assertEqual(feed_chunks(sniffer(250), FC06_WRITE, FC06_WRITE), [FC06_WRITE])
        self.assertEqual(feed_chunks(sniffer(0), FC06_WRITE, FC06_WRITE), [FC06_WRITE, FC06_WRITE])

    def test_split_hcp4_temperature_write_reaches_the_decoder(self):
        gateway = Gateway.__new__(Gateway)
        gateway.state = {}
        gateway.mqtt_enabled = False
        gateway.prefix = "dantherm/hch5"
        gateway.retain = True
        target = sniffer()
        for frame in feed_chunks(target, FC16_REQUEST[:5], FC16_REQUEST[5:]):
            gateway.decode(frame)
        self.assertEqual(gateway.state["outdoor_temp"], 14.15)
        self.assertEqual(gateway.state["supply_temp"], 20.94)
        self.assertEqual(gateway.state["hrc2_t5_temperature"], 23.40)


if __name__ == "__main__":
    unittest.main()
