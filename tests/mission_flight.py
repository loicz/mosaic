#!/usr/bin/env python3
"""Real single-UAV autonomous deployment/recall integration test, no animation."""
from __future__ import annotations
import argparse
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from mission_agent import run_agent
from mission_sitl import Sitl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--px4', type=Path, default=Path('/work/PX4-Autopilot'))
    parser.add_argument('--binary', type=Path, default=Path('/work/mosaic-build/mosaic-mission-compute'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    scene = json.loads((root/'config/mission-rescue.json').read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    partition = 'mosaic-flight-'+str(os.getpid())
    os.environ['GZ_PARTITION'] = partition
    os.environ['GZ_IP'] = '127.0.0.1'
    sitl = Sitl(scene, args.output, args.px4, partition, count=1)
    parent, child = mp.Pipe()
    prior = {key: scene[key] for key in ('walls', 'bounds', 'flight_height')}
    worker = mp.Process(target=run_agent, args=(0, scene['drones'][0], prior, child, args.binary, root/'models/mission-lidar.json'))
    records = []; sent = False; recalled = False; done = False
    try:
        sitl.start_world(); worker.start(); child.close(); sitl.start_flight_controllers()
        deadline = time.monotonic()+250
        last_state = None
        while time.monotonic() < deadline:
            if parent.poll(.2):
                state = parent.recv(); records.append(state)
                if state['state'] != last_state or len(records) % 50 == 0:
                    print(json.dumps(state, ensure_ascii=False), flush=True); last_state = state['state']
                if state['state'] == 'idle' and not sent:
                    parent.send({'op': 'deploy', 'site': scene['sites'][0]}); sent = True
                if state['state'] == 'anchor' and not recalled:
                    parent.send({'op': 'recall'}); recalled = True
                if state['state'] == 'returned': done = True; break
            if worker.exitcode is not None: raise RuntimeError('onboard process exited')
        (args.output/'telemetry.json').write_text(json.dumps(records, ensure_ascii=False))
        assert done, 'autonomous mission did not complete within 250 wall seconds'
        assert max(r['inferences'] for r in records)>0, 'local model never ran'
        assert any(r['anchor'] is not None for r in records), 'no calibrated anchor'
        print('PASS real PX4/Gazebo deploy, local sensing/inference, perch and return')
    finally:
        if worker.is_alive():
            parent.send({'op': 'stop'}); worker.join(5)
            if worker.is_alive(): worker.terminate(); worker.join(3)
        parent.close(); sitl.close()


if __name__ == '__main__':
    mp.set_start_method('spawn')
    main()
