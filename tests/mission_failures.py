#!/usr/bin/env python3
"""Component regressions for MA-1 failures; these do not certify flight."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from mission_runtime import Mission
from mission_mapping import LidarMap
from mission_power import Battery


class Pipe:
    def __init__(self):
        self.incoming = []
        self.sent = []

    def poll(self): return bool(self.incoming)
    def recv(self): return self.incoming.pop(0)
    def send(self, message): self.sent.append(copy.deepcopy(message))
    def close(self): pass


class SimulatedPower(unittest.TestCase):
    def test_clock_pause_does_not_refresh_and_armed_discharge_is_bounded(self):
        battery = Battery()
        self.assertEqual(battery.sample(1., False)['remaining'], 100)
        self.assertIsNone(battery.sample(1., True))
        self.assertIsNone(battery.sample(.5, True))
        self.assertEqual(battery.sample(16., True)['remaining'], 75)
        self.assertEqual(battery.sample(90., True)['remaining'], 50)
        self.assertEqual(battery.sample(91., False)['remaining'], 100)


class MissionFailures(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='mosaic-regression-')
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        scene = json.loads((ROOT/'config/mission-rescue.json').read_text())
        with patch('mission_runtime.Compute'), patch('mission_runtime.Sitl'):
            self.mission = Mission(scene, directory, directory, directory, ROOT)
        m = self.mission
        m.radio = Mock(time=100., start=100., disabled_nodes=set())
        m.radio.metrics.return_value = {}
        m.phase = 'tracking'
        m.compute.call.return_value = dict(position=scene['destination']['position'], used=['D1','D2','D3'])
        m.commanded = {d['id'] for d in scene['drones'][:5]}
        m.assignments = [(d['id'], s) for d, s in zip(scene['drones'], m.selected)]
        self.enabled = True
        self.absent = set()
        self.sequence = 0
        def observe(anchors, interference):
            if not self.enabled: return []
            output = []
            for person in scene['roster']:
                self.sequence += 1
                output.append((dict(id=person['id'], sequence=self.sequence, time=m.radio.time,
                    ranges=[dict(id=a['id']) for a in anchors if a['id'] not in self.absent]), [20,14.7,1.1]))
            return output
        m.radio.observe.side_effect = observe
        for index, drone in enumerate(scene['drones']):
            identity = drone['id']; anchor = [*scene['sites'][index]['position'], .5] if index < 5 else None
            m.connections[identity] = Pipe()
            m.telemetry[identity] = dict(id=identity, time=100., state='anchor' if anchor else 'idle',
                                        anchor=anchor, position=anchor, armed=False)
            if anchor:
                m.anchor_sites[identity] = dict(id=identity, position=anchor)
                m.anchor_seen[identity] = 100.
        m.visible = copy.deepcopy(m.telemetry)
        self.addCleanup(m.close)

    def advance(self, seconds):
        for _ in range(round(seconds*10)):
            self.mission.radio.time = round(self.mission.radio.time+.1, 6)
            self.mission.tick()

    def test_missing_ranges_reset_arrival_and_recover_only_with_new_fixes(self):
        m = self.mission
        m.tick(); self.advance(1.)
        self.enabled = False; self.advance(5.)
        self.assertEqual(m.phase, 'tracking')
        self.assertIsNone(m.arrival_since)
        self.assertTrue(all(p['status']=='last_known' for p in m.personnel.values()))
        self.assertIsNone(m.failed)  # Whole receiver outage is not one failed node.
        self.enabled = True; self.advance(1.)
        self.assertEqual(m.phase, 'tracking')
        self.advance(2.)
        self.assertEqual(m.phase, 'objective_complete')

    def test_duplicate_packets_cannot_refresh_positions(self):
        m = self.mission
        packets = m.radio.observe([], False)
        m.radio.observe.side_effect = lambda *_: packets
        m.tick(); self.advance(5.)
        self.assertEqual(m.phase, 'tracking')
        self.assertTrue(all(p['time']==100. for p in m.personnel.values()))

    def test_trail_preserves_failed_fix_and_missing_packet_gaps(self):
        m = self.mission
        m.tick(); self.advance(.3)
        self.assertNotIn(None, m.personnel['R1']['trail'])
        m.compute.call.return_value = dict(position=None)
        self.advance(.5)
        m.compute.call.return_value = dict(position=[16.8,10.4], used=['D1','D2','D3'])
        self.advance(.3)
        self.assertEqual(m.personnel['R1']['trail'].count(None), 1)
        self.enabled = False; self.advance(2.)
        self.enabled = True; self.advance(.3)
        self.assertEqual(m.personnel['R1']['trail'].count(None), 2)
        self.assertEqual(m.personnel['R1']['position'], [16.8,10.4])
        self.assertEqual(m.state['people'][0]['trail'], m.personnel['R1']['trail'])

    def test_clock_advancing_during_sensor_generation_is_not_future_data(self):
        m = self.mission; observe = m.radio.observe.side_effect
        def advancing(*args):
            m.radio.time += .01
            return observe(*args)
        m.radio.observe.side_effect = advancing
        m.tick()
        self.assertEqual(len(m.personnel), 3)
        self.assertTrue(all(p['status']=='current' for p in m.personnel.values()))

    def test_transport_discards_both_directions_and_outage_backlog(self):
        m = self.mission; m.radio.start = None
        m.handle(dict(op='disconnect'))
        incoming = dict(m.telemetry['D1'], time=101., position=[99,99,99])
        m.connections['D1'].incoming.append(incoming)
        self.advance(1.)
        self.assertNotEqual(m.telemetry['D1']['position'], incoming['position'])
        self.assertFalse(m.send('D1', dict(op='recall')))
        self.assertEqual(m.connections['D1'].sent, [])
        m.connections['D1'].incoming.append(dict(incoming, time=124.9))
        m.radio.time = 125.; m.tick()
        self.assertNotEqual(m.telemetry['D1']['position'], incoming['position'])
        m.connections['D1'].incoming.append(dict(incoming, time=125.1))
        self.advance(.1)
        self.assertEqual(m.telemetry['D1']['position'], incoming['position'])

    def test_unknown_node_detected_during_disconnect_without_identity_hint(self):
        m = self.mission
        m.tick(); m.handle(dict(op='disconnect')); self.absent = {'D1'}
        self.advance(1.9)
        self.assertEqual(m.failed, 'D1')
        self.assertNotIn('D1', m.anchor_sites)
        self.assertTrue(all(p['status']=='current' for p in m.personnel.values()))
        self.assertEqual(m.connections['D6'].sent, [])
        self.advance(4.)
        self.assertIsNone(m.recovery_time)
        self.advance(20.)
        self.assertIsNotNone(m.recovery_time)
        self.assertEqual(len(m.connections['D6'].sent), 1)
        self.assertEqual(m.connections['D6'].sent[0]['op'], 'deploy')
        self.advance(1.)
        self.assertEqual(len(m.connections['D6'].sent), 1)

    def test_leaving_radio_range_is_not_a_failure_and_reentry_gets_a_new_window(self):
        m = self.mission
        m.compute.call.return_value = dict(position=[1.5,2.8], used=['D1','D2','D3'])
        self.absent = {'D4'}  # S4 is outside the west assembly area's range.
        m.tick(); self.advance(5.)
        self.assertIsNone(m.failed)
        m.compute.call.return_value = dict(position=[20,14.7], used=['D1','D2','D3'])
        self.advance(.8)
        self.assertIsNone(m.failed)
        self.advance(1.)
        self.assertEqual(m.failed,'D4')


class MappingFailures(unittest.TestCase):
    def sample(self, stamp, distance=2., position_stamp=None):
        return ([distance]*361, -math.pi, math.pi/180, stamp, [5.,5.,1.8], 0.,
                stamp if position_stamp is None else position_stamp)

    def test_duplicate_scan_is_not_projected_from_a_new_pose(self):
        local = LidarMap([], [0,0]); sample = self.sample(1.)
        self.assertTrue(local.update(sample)); original = local.cells.copy()
        shifted = list(sample); shifted[4] = [50,50,1.8]
        self.assertFalse(local.update(shifted)); self.assertEqual(local.cells, original)

    def test_stale_odometry_cannot_create_obstacles_and_fresh_rays_clear_them(self):
        local = LidarMap([], [0,0])
        self.assertFalse(local.update(self.sample(5., position_stamp=0.)))
        self.assertEqual(local.cells, set())
        local.update(self.sample(6.)); self.assertTrue(local.cells)
        local.update(self.sample(7., distance=math.inf))
        self.assertEqual(local.cells, set())


if __name__ == '__main__': unittest.main()
