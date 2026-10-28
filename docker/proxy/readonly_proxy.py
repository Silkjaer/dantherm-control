#!/usr/bin/env python3
"""Guarded fan-out proxy for an RS485 TCP adapter.

Bus -> clients: every byte is forwarded to every client.
Clients -> bus: by default nothing is forwarded. Each client stream is split
into Modbus RTU request frames, and only frames matching ALLOW are written to
the adapter. Every client frame is logged to TX_LOG as SENT or DROPPED, with
the reason, so the log shows exactly what reached the bus.

ALLOW is a comma-separated list, empty by default (read-only):
  read                 FC03/FC04 read requests to any slave
  write:SLAVE:REG/REG  FC06 single-register writes to those registers only,
                       for example write:1:66/67/68/76
FC16 block writes and anything unparseable are always dropped.
"""
import os
import select
import socket
import sys
import time

UPSTREAM = os.environ.get("UPSTREAM", "192.168.1.200:4196")
LISTEN = os.environ.get("LISTEN", "0.0.0.0:4300")
ALLOW = os.environ.get("ALLOW", "")
TX_LOG = os.environ.get("TX_LOG", "/logs/proxy-tx.log")


def addr(text):
    host, port = text.rsplit(":", 1)
    return host, int(port)


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def parse_allow(text):
    reads, writes = False, set()
    for item in filter(None, (part.strip() for part in text.split(","))):
        if item == "read":
            reads = True
        elif item.startswith("write:"):
            _, slave, regs = item.split(":")
            writes.update((int(slave, 0), int(reg, 0)) for reg in regs.split("/"))
        else:
            raise SystemExit(f"Unknown ALLOW item: {item}")
    return reads, writes


ALLOW_READS, ALLOW_WRITES = parse_allow(ALLOW)


def verdict(frame):
    """Return (forward, reason) for one CRC-valid request frame."""
    slave, function = frame[0], frame[1]
    if function in (3, 4):
        return ALLOW_READS, "read" if ALLOW_READS else "reads not allowed"
    if function == 6:
        register = int.from_bytes(frame[2:4], "big")
        if (slave, register) in ALLOW_WRITES:
            return True, f"write {slave}:{register} allowed"
        return False, f"write {slave}:{register} not allowed"
    return False, f"function {function} never allowed"


def take_frames(buffer):
    """Split complete request frames off the front of buffer.

    Yields (frame, None) for a CRC-valid frame and (bytes, reason) for bytes
    that had to be discarded to resynchronise.
    """
    while len(buffer) >= 8:
        function = buffer[1]
        if function in (3, 4, 6):
            length = 8
        elif function == 16:
            length = 9 + buffer[6]
        else:
            yield bytes(buffer[:1]), "unparseable byte"
            del buffer[:1]
            continue
        if len(buffer) < length:
            return
        frame = bytes(buffer[:length])
        if crc16(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
            yield bytes(buffer[:1]), "bad CRC, resync"
            del buffer[:1]
            continue
        del buffer[:length]
        yield frame, None


def connect_upstream():
    while True:
        try:
            s = socket.create_connection(addr(UPSTREAM), timeout=5)
            s.setblocking(False)
            log(f"upstream connected {UPSTREAM}")
            return s
        except OSError as e:
            log(f"upstream {UPSTREAM} failed: {e}; retry in 3s")
            time.sleep(3)


def main():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(addr(LISTEN))
    listener.listen(4)
    listener.setblocking(False)
    allowed = ", ".join(
        (["reads"] if ALLOW_READS else [])
        + [f"FC06 {s}:{r}" for s, r in sorted(ALLOW_WRITES)]
    ) or "nothing (read-only)"
    log(f"listening on {LISTEN}; client->bus allowed: {allowed}; log {TX_LOG}")

    os.makedirs(os.path.dirname(TX_LOG), exist_ok=True)
    tx_log = open(TX_LOG, "a", buffering=1)
    upstream = connect_upstream()
    clients = {}  # socket -> (peer, pending bytes)
    sent = dropped = rx = 0
    last_stat = time.time()

    while True:
        readable, _, _ = select.select([listener, upstream, *clients], [], [], 1.0)
        for s in readable:
            if s is listener:
                c, peer = listener.accept()
                c.setblocking(False)
                clients[c] = (f"{peer[0]}:{peer[1]}", bytearray())
                log(f"client connected {clients[c][0]}")
            elif s is upstream:
                try:
                    data = upstream.recv(4096)
                except OSError:
                    data = b""
                if not data:
                    log("upstream closed; reconnecting")
                    upstream.close()
                    upstream = connect_upstream()
                    continue
                rx += len(data)
                for c in list(clients):
                    try:
                        c.sendall(data)
                    except OSError:
                        log(f"client gone {clients.pop(c)[0]}")
                        c.close()
            else:
                peer, pending = clients[s]
                try:
                    data = s.recv(4096)
                except OSError:
                    data = b""
                if not data:
                    log(f"client gone {peer}")
                    clients.pop(s)
                    s.close()
                    continue
                pending.extend(data)
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                for frame, problem in take_frames(pending):
                    forward, reason = (False, problem) if problem else verdict(frame)
                    if forward:
                        try:
                            upstream.sendall(frame)
                        except OSError as error:
                            forward, reason = False, f"upstream send failed: {error}"
                    sent += len(frame) if forward else 0
                    dropped += 0 if forward else len(frame)
                    tx_log.write(f"{stamp} {peer} {'SENT' if forward else 'DROPPED'} {frame.hex(' ')} ({reason})\n")
        if time.time() - last_stat >= 60:
            log(f"bus->clients {rx} bytes; clients->bus sent {sent}, dropped {dropped} bytes; {len(clients)} client(s)")
            last_stat = time.time()


if __name__ == "__main__":
    sys.exit(main())
