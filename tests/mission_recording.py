#!/usr/bin/env python3
"""Regress automatic exit between two throttled recording snapshots."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from mission_runtime import Mission
from mission_replay import Replay


class IndexedReplayTests(unittest.TestCase):
    def test_index_keeps_trails_in_individual_frames_and_retries_partial_writes(self):
        with tempfile.TemporaryDirectory(prefix='mosaic-replay-') as temporary:
            path=Path(temporary)/'session.jsonl'
            first=dict(time=1.,phase='tracking',people=[dict(id='R1',trail=[[1,2],None,[2,3]])])
            second=dict(time=2.,phase='evacuating',token='never-public',people=[dict(id='R1',trail=[[1,2],None,[2,3],[3,4]])])
            final=json.dumps(dict(kind='state',value=second))+'\n'
            path.write_text(json.dumps(dict(kind='state',value=first))+'\n'+
                            json.dumps(dict(kind='event',value=dict(code='task')))+'\n'+final[:30])
            replay=Replay(path)
            self.assertEqual(replay.index()['frames'],[dict(time=1.,phase='tracking')])
            self.assertEqual(replay.frame(0),first)
            with self.assertRaises(IndexError):replay.frame(1)
            with self.assertRaises(IndexError):replay.frame(-1)
            with path.open('a') as stream:stream.write(final[30:])
            self.assertEqual(len(replay.index()['frames']),2)
            self.assertEqual(len(replay.index()['frames']),2)
            self.assertEqual(replay.frame(1)['people'],second['people'])
            self.assertNotIn('token',replay.frame(1))


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='mosaic-recording-')
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.scene = json.loads((ROOT / 'config/mission-rescue.json').read_text())
        # No fake flight evidence: this unit fixture only controls the recorder
        # clock and terminal telemetry to exercise the real tick/close methods.
        with patch('mission_runtime.Compute'), patch('mission_runtime.Sitl'):
            self.mission = Mission(self.scene, self.path, self.path, self.path, ROOT)

    def test_completion_between_snapshots_is_flushed_without_control_token(self):
        mission = self.mission
        mission.radio = Mock(time=42.0, start=None)
        mission.radio.metrics.return_value = {}
        mission.phase = 'recalling'
        mission.commanded = {'D1'}
        mission.recalled = {'D1'}
        mission.telemetry = {
            d['id']: dict(id=d['id'], state='returned' if d['id']=='D1' else 'idle',
                          time=42.0, anchor=None, armed=False)
            for d in self.scene['drones']
        }
        mission.visible = copy.deepcopy(mission.telemetry)
        mission.write_record('state', dict(phase='recalling'))
        mission.last_snapshot = 100.0
        try:
            with patch('mission_runtime.time.monotonic', return_value=100.05):
                mission.tick()
            self.assertEqual(mission.phase, 'complete')
            before = [json.loads(line) for line in (self.path/'session.jsonl').read_text().splitlines()]
            self.assertEqual([r['value'] for r in before if r['kind']=='state'][-1]['phase'], 'recalling')
        finally:
            mission.close()
        records = [json.loads(line) for line in (self.path/'session.jsonl').read_text().splitlines()]
        final = [r['value'] for r in records if r['kind']=='state'][-1]
        self.assertEqual(final['phase'], 'complete')
        self.assertEqual(final['active_anchors'], 0)
        self.assertTrue(all(d['state'] in ('returned', 'idle') and not d['armed'] for d in final['drones']))
        self.assertNotIn('token', final)
        self.assertEqual(json.loads((self.path/'metrics.json').read_text())['phase'], final['phase'])

    def test_close_before_start_does_not_invent_completion(self):
        self.mission.close()
        records = [json.loads(line) for line in (self.path/'session.jsonl').read_text().splitlines()]
        self.assertEqual([r for r in records if r['kind']=='state'], [])
        self.assertEqual(json.loads((self.path/'metrics.json').read_text())['phase'], 'starting')


if __name__ == '__main__':
    unittest.main()
