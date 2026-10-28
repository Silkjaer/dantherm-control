# Guarded Docker test

Runs HCH5 Control in Docker against a live HCH5 bus through an RS485-to-
Ethernet adapter in transparent TCP mode. By default it cannot write to the
bus, which is useful for evaluating the WebUI and the controller's decisions
while HCP4 is still the bus master. With HCP4 disconnected, `PROXY_ALLOW`
lets the controller take over one step at a time.

```text
RS485 adapter (host:port)
      │  read only – the proxy never writes to it
rs485-readonly  ── forwards only what PROXY_ALLOW permits, logs every frame
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

`PROXY_ALLOW` decides what the controller may send (empty = nothing):

| `PROXY_ALLOW` | Reaches the bus |
|---|---|
| *(empty)* | nothing |
| `read` | FC03/FC04 read requests |
| `read,write:1:66/67/68/76` | reads, plus FC06 writes to the fan pair (66/67), bypass (68) and register 76 |

FC16 block writes (HAC1) are never forwarded.

Open http://localhost:8088 and create the first account.

## What to check

- `docker compose logs controller | grep MASTER` – with HCP4 connected the
  controller reports `MASTER UNKNOWN -> HCP4` and keeps its own writes paused.
- `logs/proxy-tx.log` – every frame the controller sent, marked SENT or
  DROPPED with the reason. With HCP4 connected it should stay empty.
- `data/` – controller state, history and WebUI users, kept across restarts.

The adapter must allow a second TCP client if Home Assistant is already
connected to it.
