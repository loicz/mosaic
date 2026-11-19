#!/usr/bin/env python3
"""Personnel motion geometry, independent of Gazebo and the position solver."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from mission_radio import RadioSimulation, validate_personnel_route
from mission_runtime import Mission


class PersonnelRoute(unittest.TestCase):
    def setUp(self):
        self.scene = json.loads((ROOT/'config/mission-rescue.json').read_text())

    def test_reference_motion_stays_clear_for_every_person(self):
        validate_personnel_route(self.scene)
        radio = RadioSimulation.__new__(RadioSimulation)
        radio.scene = self.scene; radio.start = 0.
        route = self.scene['personnel_route']
        duration = sum(math.dist(a,b) for a,b in zip(route,route[1:]))/.65
        clearance = self.scene['personnel_clearance']
        boxes = self.scene['walls']+[o['box'] for o in self.scene['obstacles']]
        for index in range(len(self.scene['roster'])):
            previous = None
            for step in range(math.ceil((duration+index*1.7+1)*100)):
                radio.time = step*.01
                point, done = radio._person(index)
                for x,y,w,h in boxes:
                    self.assertFalse(x-clearance<=point[0]<=x+w+clearance and
                                     y-clearance<=point[1]<=y+h+clearance, (index,radio.time,point))
                if previous is not None:
                    self.assertLessEqual(math.dist(previous,point), .0065+1e-9)
                previous = point
            self.assertTrue(done)
            self.assertEqual(point[:2], self.scene['destination']['position'])

    def test_original_cross_wall_route_rejected_before_process_start(self):
        self.scene['personnel_route'][2] = [13.5,10.4]
        with patch('mission_runtime.Compute') as compute, patch('mission_runtime.Sitl') as sitl:
            with self.assertRaisesRegex(ValueError, 'segment 2 intersects'):
                Mission(self.scene, None, None, None, None)
            compute.assert_not_called(); sitl.assert_not_called()

    def test_thin_obstacle_between_clear_endpoints_is_rejected(self):
        self.scene['obstacles'].append(dict(box=[14,5.5,.01,1]))
        with self.assertRaisesRegex(ValueError, 'segment 2 intersects'):
            validate_personnel_route(self.scene)

    def test_clear_centerline_with_insufficient_body_margin_is_rejected(self):
        self.scene['personnel_route'] = [[12.3,5],[12.3,6]]
        with self.assertRaisesRegex(ValueError, 'clearance'):
            validate_personnel_route(self.scene)

    def test_invalid_and_degenerate_routes_are_rejected(self):
        for route in ([], [[12.6,3]], [[12.6,3],[12.6,3]],
                      [[math.nan,3],[12.6,6]], [[12.6,3],[math.inf,6]],
                      [[-.1,3],[12.6,6]], [[.2,3],[.2,6]]):
            with self.subTest(route=route), self.assertRaises(ValueError):
                scene = copy.deepcopy(self.scene); scene['personnel_route'] = route
                validate_personnel_route(scene)
        for clearance in (0, -.1, math.nan, math.inf):
            with self.subTest(clearance=clearance), self.assertRaises(ValueError):
                scene = copy.deepcopy(self.scene); scene['personnel_clearance'] = clearance
                validate_personnel_route(scene)


if __name__ == '__main__': unittest.main()
