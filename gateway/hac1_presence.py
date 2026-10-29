#!/usr/bin/env python3
"""Whether a HAC1 module (slave 0x40) is installed, learned from the bus.

Not every HCH5 MK1 has a HAC1. Without one, every HAC1 read is retried and
times out (about 0.7 s each, several per poll cycle) and every HAC1 write
waits for an acknowledgement that never comes. This tracks what the bus has
shown so that traffic can stop once the module is known to be missing.

* present: a response or write acknowledgement from 0x40 was seen, or HCP4
  reported HAC1 connected (register 146 = 1).
* absent: HCP4 reported HAC1 not connected (register 146 = 0), or HAC1 never
  answered MISSES_TO_ABSENT active reads in a row while the unit itself did.
* unknown: nothing either way yet; HAC1 traffic continues so it can be found.

A module that has answered once is never declared absent from missed reads,
so installations with HAC1 behave exactly as before. While absent, one probe
read is allowed every PROBE_INTERVAL seconds, so a HAC1 that is connected
later is found again.
"""
from __future__ import annotations

import time

HAC1_SLAVE = 0x40


class Hac1Presence:
    UNKNOWN = "unknown"
    PRESENT = "present"
    ABSENT = "absent"
    MISSES_TO_ABSENT = 3
    PROBE_INTERVAL = 600.0

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.state = self.UNKNOWN
        self.misses = 0
        self.last_probe = 0.0

    @property
    def absent(self) -> bool:
        return self.state == self.ABSENT

    @property
    def present(self) -> bool:
        return self.state == self.PRESENT

    def seen(self) -> None:
        """HAC1 answered: a read response or a write acknowledgement."""
        self.state = self.PRESENT
        self.misses = 0

    def reported(self, connected: bool) -> None:
        """HCP4's own view of HAC1, from its register 146 writes."""
        if connected:
            self.seen()
        elif self.state != self.ABSENT:
            self.state = self.ABSENT
            self.last_probe = self.clock()

    def missed(self, *, unit_answering: bool) -> None:
        """An active HAC1 read got no answer.

        Only counted while the unit itself answers, so a dead bus is never
        mistaken for a missing module.
        """
        if self.state != self.UNKNOWN or not unit_answering:
            return
        self.misses += 1
        if self.misses >= self.MISSES_TO_ABSENT:
            self.state = self.ABSENT
            self.last_probe = self.clock()

    def allow_read(self) -> bool:
        """Whether an active HAC1 read may go on the bus now."""
        if self.state != self.ABSENT:
            return True
        now = self.clock()
        if now - self.last_probe >= self.PROBE_INTERVAL:
            self.last_probe = now
            return True
        return False
