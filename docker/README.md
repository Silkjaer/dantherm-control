# Read-only Docker test

Runs HCH5 Control in Docker against a live HCH5 bus through an RS485-to-
Ethernet adapter in transparent TCP mode, without being able to write to the
bus. Useful for evaluating the WebUI and the controller's decisions while
HCP4 is still the bus master.

```text
RS485 adapter (host:port)
      │  read only – the proxy never writes to it
rs485-readonly  ── drops and logs every byte the controller sends
      │
controller      ── WebUI on http://localhost:8088
```

## Start and stop

```bash
cd docker
RS485_ADAPTER=192.168.1.200:4196 docker compose up -d --build
docker compose down
```

Or put `RS485_ADAPTER=192.168.1.200:4196` in `docker/.env`.

Open http://localhost:8088 and create the first account.

## What to check

- `docker compose logs controller | grep MASTER` – with HCP4 connected the
  controller reports `MASTER UNKNOWN -> HCP4` and keeps its own writes paused.
- `logs/dropped-writes.log` – every byte the controller tried to send. With
  HCP4 connected it should stay empty.
- `data/` – controller state, history and WebUI users, kept across restarts.

The adapter must allow a second TCP client if Home Assistant is already
connected to it.
