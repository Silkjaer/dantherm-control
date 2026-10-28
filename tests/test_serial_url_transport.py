import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

import serial

from dantherm_gateway import RtuSniffer, open_serial_port


def test_url_port_opens_through_serial_for_url():
    ser = open_serial_port("loop://", 19200, parity=serial.PARITY_EVEN, timeout=0.1, exclusive=True)
    try:
        assert ser.is_open
        ser.write(b"\x01\x03")
        assert ser.read(2) == b"\x01\x03"
    finally:
        ser.close()


def test_rtu_sniffer_accepts_a_url_port():
    ser = RtuSniffer("loop://", 19200, "E", 0).open()
    try:
        assert ser.is_open
        assert ser.parity == serial.PARITY_EVEN
    finally:
        ser.close()
