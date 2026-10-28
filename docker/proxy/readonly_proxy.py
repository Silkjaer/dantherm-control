#!/usr/bin/env python3
"""Read-only fan-out proxy for the Waveshare RS485 TCP adapter.

Bytes flow one way only: adapter -> clients. Anything a client sends is read,
logged as hex to DROP_LOG and discarded. The upstream socket is never written
to, so nothing behind this proxy can put a byte on the RS485 bus.
"""
import os
import select
import socket
import sys
import time

UPSTREAM = os.environ.get("UPSTREAM", "192.168.1.200:4196")
LISTEN = os.environ.get("LISTEN", "0.0.0.0:4300")
DROP_LOG = os.environ.get("DROP_LOG", "/logs/dropped-writes.log")


def addr(text):
    host, port = text.rsplit(":", 1)
    return host, int(port)


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def connect_upstream():
    while True:
        try:
            s = socket.create_connection(addr(UPSTREAM), timeout=5)
            s.setblocking(False)
            log(f"upstream connected {UPSTREAM} (read-only)")
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
    log(f"listening on {LISTEN}; client->bus bytes are dropped and logged to {DROP_LOG}")

    os.makedirs(os.path.dirname(DROP_LOG), exist_ok=True)
    drop_log = open(DROP_LOG, "a", buffering=1)
    upstream = connect_upstream()
    clients = {}  # socket -> peer
    dropped = 0
    rx = 0
    last_stat = time.time()

    while True:
        readable, _, _ = select.select([listener, upstream, *clients], [], [], 1.0)
        for s in readable:
            if s is listener:
                c, peer = listener.accept()
                c.setblocking(False)
                clients[c] = f"{peer[0]}:{peer[1]}"
                log(f"client connected {clients[c]}")
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
                        log(f"client gone {clients.pop(c)}")
                        c.close()
            else:
                try:
                    data = s.recv(4096)
                except OSError:
                    data = b""
                if not data:
                    log(f"client gone {clients.pop(s)}")
                    s.close()
                    continue
                # The whole point of this proxy: never forward to upstream.
                dropped += len(data)
                drop_log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {clients[s]} {data.hex(' ')}\n")
        if time.time() - last_stat >= 60:
            log(f"bus->clients {rx} bytes, clients->bus DROPPED {dropped} bytes, {len(clients)} client(s)")
            last_stat = time.time()


if __name__ == "__main__":
    sys.exit(main())
