"""Simulation-only battery measurements, independent of command transport.

Uses the reference SITL model: four cells, 60 seconds from full to empty
while armed, a 50% floor, and recharge while disarmed. This is not an
endurance model. PX4 still checks received battery health and freshness.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import signal
import time


class Battery:
    def __init__(self):
        self.remaining = 1.
        self.last = None

    def sample(self, now, armed):
        # A paused clock must not manufacture fresh sensor measurements.
        if self.last is not None and now <= self.last:
            return None
        elapsed = 0. if self.last is None else now-self.last
        self.last = now
        self.remaining = max(.5, self.remaining-elapsed/60.) if armed else 1.
        return dict(remaining=round(self.remaining*100),
                    cell_mv=round((3.6+.45*self.remaining)*1000))


def main():
    from gz.transport13 import Node
    from gz.msgs10.clock_pb2 import Clock
    from pymavlink import mavutil
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, required=True)
    parser.add_argument('--journal', type=Path, required=True)
    args = parser.parse_args()
    clock = [0.]; stopped = [False]
    def on_clock(message):
        clock[0] = message.sim.sec+message.sim.nsec*1e-9
    def stop(*_): stopped[0] = True
    for sig in (signal.SIGINT, signal.SIGTERM): signal.signal(sig, stop)
    node = Node(); node.subscribe(Clock, '/world/mosaic/clock', on_clock)
    # The simulation port is separate from each onboard controller's link.
    links = [mavutil.mavlink_connection(f'udpin:127.0.0.1:{14030+i}',
             source_system=i+1, source_component=mavutil.mavlink.MAV_COMP_ID_BATTERY)
             for i in range(args.count)]
    batteries = [Battery() for _ in links]; armed = [False]*len(links)
    last_publish = 0.
    try:
        with args.journal.open('w') as journal:
            while not stopped[0]:
                now = clock[0]
                for i, link in enumerate(links):
                    while (message := link.recv_match(blocking=False)) is not None:
                        if (message.get_type() == 'HEARTBEAT' and
                            message.get_srcSystem() == i+1 and message.get_srcComponent() == 1):
                            armed[i] = bool(message.base_mode & 128)
                if now-last_publish >= .2:
                    last_publish = now
                    for i, (battery, link) in enumerate(zip(batteries, links)):
                        sample = battery.sample(now, armed[i])
                        if sample is None: continue
                        link.mav.battery_status_send(0, 0, 3, 32767,
                            [sample['cell_mv']]*4+[65535]*6, -1, -1, -1, sample['remaining'])
                        journal.write(json.dumps(dict(time=now, id=f'D{i+1}', armed=armed[i], **sample))+'\n')
                    journal.flush()
                time.sleep(.02)
    finally:
        node.unsubscribe('/world/mosaic/clock')
        for link in links: link.close()


if __name__ == '__main__': main()
