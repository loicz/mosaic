#!/usr/bin/env python3
"""Evacuation safety regressions. Component fixtures are not flight evidence."""
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
from mission_coverage import coverage
from mission_radio import RadioSimulation, validate_evacuation
from mission_runtime import Mission, choose_sites
from mission_failures import Pipe


class Evacuation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='mosaic-evacuation-')
        self.addCleanup(temporary.cleanup)
        self.scene = json.loads((ROOT/'config/mission-rescue.json').read_text())
        directory = Path(temporary.name)
        with patch('mission_runtime.Compute'), patch('mission_runtime.Sitl'):
            self.m = Mission(self.scene, directory, directory, directory, ROOT)
        m = self.m
        m.radio = Mock(time=100., start=60., disabled_nodes=set())
        m.radio.metrics.return_value = {}
        m.radio.observe.return_value = []
        m.phase = 'objective_complete'
        m.arrival_since = 97.
        for drone, site in zip(self.scene['drones'], m.selected):
            identity = drone['id']; position = [*site['position'], .5]
            m.assignments.append((identity,site)); m.commanded.add(identity)
            m.anchor_sites[identity] = dict(id=identity,position=position)
            m.anchor_seen[identity] = 100.
            m.telemetry[identity] = dict(id=identity,time=100.,state='anchor',anchor=position,
                                         position=position,armed=False,target=site)
        m.telemetry['D6'] = dict(id='D6',time=100.,state='idle',anchor=None,position=[17,1.8,.1],armed=False)
        m.visible = copy.deepcopy(m.telemetry)
        m.connections.update({d['id']:Pipe() for d in self.scene['drones']})
        self.fresh(self.scene['destination']['position'])
        self.addCleanup(m.close)

    def fresh(self, position, used=None):
        m = self.m
        for identity in m.anchor_sites: m.anchor_seen[identity] = m.radio.time
        m.personnel = {p['id']:dict(id=p['id'],time=m.radio.time,sequence=i+1,
                      status='current',position=position.copy(),used=used or list(m.anchor_sites),trail=[position.copy()])
                      for i,p in enumerate(self.scene['roster'])}

    def test_indoor_objective_and_withdrawing_personnel_cannot_recall(self):
        m = self.m
        for phase in ('tracking','objective_complete','planning_evacuation','evacuating'):
            m.phase = phase; m.handle(dict(op='recall'))
            self.assertEqual(m.phase,phase)
            self.assertEqual(m.events[-1]['code'],'recall_rejected')
            self.assertFalse(any(p.sent for p in m.connections.values()))

    def test_missing_or_old_person_cannot_complete_evacuation(self):
        m = self.m; m.phase = 'evacuating'
        m.exit_plan = dict(self.scene['evacuation']['primary'],name='primary')
        destination = m.exit_plan['route'][-1]
        self.fresh(destination); m.tick()
        m.radio.time += 1; self.fresh(destination); m.tick()
        del m.personnel['R3']; m.radio.time += 1; m.tick()
        self.assertIsNone(m.exit_since)
        self.assertEqual(m.phase,'evacuating')
        for step in range(4):
            m.radio.time += 1; self.fresh(destination)
            if step == 0: m.personnel['R3']['time'] -= 5
            m.tick()
        self.assertEqual(m.phase,'evacuated')
        m.handle(dict(op='recall'))
        self.assertEqual(m.phase,'recalling')
        self.assertEqual(m.outcome,'objective_completed')

    def test_primary_route_needs_no_additional_flight(self):
        m = self.m; m.handle(dict(op='evacuate'))
        for _ in range(4):
            self.fresh(self.scene['destination']['position'])
            m.tick(); m.radio.time += 1
        self.assertEqual(m.phase,'evacuating')
        self.assertIsNone(m.reposition)
        self.assertFalse(any(p.sent for p in m.connections.values()))
        m.radio.evacuate.assert_called_once_with(self.scene['evacuation']['primary']['route'])

    def test_declared_closure_updates_onboard_route_constraints_only_after_ack(self):
        m = self.m
        m.sitl.block_passage.return_value = False
        m.handle(dict(op='block_route'))
        self.assertFalse(m.route_blocked)
        self.assertFalse(any(p.sent for p in m.connections.values()))
        m.sitl.block_passage.return_value = True
        m.handle(dict(op='block_route'))
        self.assertTrue(m.route_blocked)
        for pipe in m.connections.values():
            self.assertEqual(pipe.sent[-1],dict(op='avoid_area',box=self.scene['evacuation']['closure']['box']))

    def test_candidate_and_old_telemetry_cannot_enable_departure(self):
        m = self.m; m.route_blocked = True; m.handle(dict(op='evacuate')); m.tick()
        self.assertEqual(m.reposition['site'],'S7')
        identity = m.reposition['id']
        self.assertEqual(m.connections[identity].sent[-1]['op'],'deploy')
        self.assertNotIn(identity,m.anchor_sites)
        m.connections[identity].incoming.append(dict(m.telemetry[identity],target=None))
        m.radio.time += .2; self.fresh(self.scene['destination']['position']); m.tick()
        self.assertNotIn(identity,m.anchor_sites)
        wrong = dict(m.telemetry['D1'],id=identity,target=self.scene['sites'][0])
        m.connections[identity].incoming.append(wrong)
        m.radio.time += .2; self.fresh(self.scene['destination']['position']); m.tick()
        self.assertNotIn(identity,m.anchor_sites)
        self.assertEqual(m.phase,'planning_evacuation')
        self.assertFalse(m.radio.evacuate.called)
        # Even a calibrated candidate needs actual accepted new ranging.
        site = self.scene['sites'][-1]
        good = dict(wrong,target=site,anchor=[*site['position'],.5],position=[*site['position'],.5])
        m.connections[identity].incoming.append(good)
        for _ in range(4):
            m.radio.time += 1
            self.fresh(self.scene['destination']['position'],used=['D1','D2','D3','D4','D5'])
            m.tick()
        self.assertFalse(m.radio.evacuate.called)
        for _ in range(4):
            m.radio.time += 1; self.fresh(self.scene['destination']['position']); m.tick()
        self.assertEqual(m.phase,'evacuating')

    def test_no_spare_only_relocates_with_current_personnel_coverage(self):
        m = self.m
        spare_site = next(s for s in self.scene['sites'] if s['id']=='S5')
        m.commanded.add('D6'); m.assignments.append(('D6',spare_site))
        m.telemetry['D6'].update(state='anchor',target=spare_site,anchor=[*spare_site['position'],.5])
        m.anchor_sites['D6'] = dict(id='D6',position=[*spare_site['position'],.5])
        m.failed = 'D1'; del m.anchor_sites['D1']; m.telemetry['D1']['state'] = 'radio_failed'
        m.route_blocked = True; m.handle(dict(op='evacuate'))
        self.fresh(self.scene['destination']['position']); m.tick()
        self.assertEqual(m.reposition['op'],'relocate')
        self.assertNotEqual(m.reposition['id'],'D1')
        self.assertGreaterEqual(len(m.anchor_sites),3)
        self.assertFalse(m.radio.evacuate.called)
        records=[json.loads(line) for line in (m.directory/'session.jsonl').read_text().splitlines()]
        handover=next(r['value'] for r in records if r['kind']=='coverage_handover')
        self.assertNotIn(m.reposition['id'],[a['id'] for a in handover['remaining']])

    def test_capacity_and_link_loss_hold_the_roster(self):
        m = self.m; m.route_blocked = True; m.handle(dict(op='evacuate'))
        m.handle(dict(op='disconnect')); m.tick()
        self.assertIsNone(m.reposition)
        m.handle(dict(op='reconnect'))
        m.commanded = {d['id'] for d in self.scene['drones']}
        self.fresh(self.scene['destination']['position'],used=['D1','D2','D3'])
        # Those three measured contributors must not be removed; other anchors
        # are unavailable, so no candidate geometry can authorize a handover.
        m.anchor_sites = {i:a for i,a in m.anchor_sites.items() if i in ('D1','D2','D3')}
        m.tick()
        self.assertIsNone(m.reposition)
        self.assertEqual(m.coverage_status,'coverage_unavailable')
        self.assertFalse(m.radio.evacuate.called)

    def test_motion_joins_without_teleport_and_routes_avoid_closure(self):
        validate_evacuation(self.scene)
        for name in ('primary','alternate'):
            radio = RadioSimulation.__new__(RadioSimulation)
            radio.scene = self.scene; radio.start = 0.; radio.time = 50.
            radio.evacuation_paths = None
            radio.closure = self.scene['evacuation']['closure'] if name=='alternate' else None
            before = [radio._person(i)[0] for i in range(3)]
            radio.evacuate(self.scene['evacuation'][name]['route'])
            self.assertEqual(before,[radio._person(i)[0] for i in range(3)])
            previous = before
            for step in range(1,1001):
                radio.time = 50+step*.1
                current = [radio._person(i)[0] for i in range(3)]
                for a,b in zip(previous,current): self.assertLessEqual(math.dist(a,b),.065+1e-8)
                previous = current
            self.assertTrue(all(p[:2]==self.scene['evacuation'][name]['route'][-1] for p in current))

    def test_route_coverage_distinguishes_fixed_and_extended_network(self):
        anchors,_ = choose_sites(self.scene)
        route = self.scene['evacuation']['alternate']['route']
        self.assertFalse(coverage(anchors,route,19)['covered'])
        self.assertTrue(coverage(anchors+[self.scene['sites'][-1]],route,19)['covered'])


if __name__ == '__main__': unittest.main()
