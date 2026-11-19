"""Simulation-only UWB sensor generation and independent error evaluation.

Only this module may read Gazebo pose truth. The positioning consumer receives
ranges, identities and timestamps, never the hidden personnel coordinates.
"""
from __future__ import annotations
import math
import random
import threading
import json


def crosses(a, b, box):
    x,y,w,h = box
    low, high = 0., 1.
    for origin, delta, minimum, maximum in ((a[0], b[0]-a[0], x, x+w), (a[1], b[1]-a[1], y, y+h)):
        if abs(delta) < 1e-10:
            if origin < minimum or origin > maximum: return False
        else:
            t0,t1 = sorted(((minimum-origin)/delta, (maximum-origin)/delta))
            low,high = max(low,t0), min(high,t1)
            if low > high: return False
    return True


def validate_personnel_route(scene):
    """Reject impossible simulated motion before starting any flight processes.

    Clearance is a conservative planar body margin for this simulation, not a
    validated physical-person model. Check whole segments, not just waypoints.
    """
    def finite(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    clearance = scene.get('personnel_clearance', .3)
    if not finite(clearance) or clearance <= 0:
        raise ValueError('personnel_clearance must be finite and positive')
    route = scene['personnel_route']
    if not isinstance(route, list) or len(route) < 2:
        raise ValueError('personnel_route needs at least two waypoints')
    minimum, maximum = scene['bounds']
    for point in route:
        if (not isinstance(point, list) or len(point) != 2 or not all(map(finite, point)) or
            not all(minimum[i]+clearance < point[i] < maximum[i]-clearance for i in range(2))):
            raise ValueError('personnel_route waypoint is invalid or outside navigable bounds')
    obstacles = scene['walls'] + [o['box'] for o in scene.get('obstacles', [])]
    expanded = []
    for box in obstacles:
        if len(box) != 4 or not all(map(finite, box)) or box[2] <= 0 or box[3] <= 0:
            raise ValueError('personnel_route obstacle must be a finite positive rectangle')
        x,y,w,h = box
        expanded.append([x-clearance, y-clearance, w+2*clearance, h+2*clearance])
    for index, (a,b) in enumerate(zip(route, route[1:]), 1):
        if math.dist(a,b) <= 1e-10:
            raise ValueError(f'personnel_route segment {index} has zero length')
        if any(crosses(a,b,box) for box in expanded):
            raise ValueError(f'personnel_route segment {index} intersects a wall or obstacle clearance')


def validate_evacuation(scene):
    evacuation = scene['evacuation']
    for name in ('primary', 'alternate'):
        route = evacuation[name]['route']
        if route[0] != scene['destination']['position']:
            raise ValueError('evacuation must start at the personnel objective')
        obstacles = list(scene.get('obstacles', []))
        if name == 'alternate': obstacles.append(evacuation['closure'])
        validate_personnel_route(dict(scene, personnel_route=route, obstacles=obstacles))
    maximum = scene['radio']['max_range']
    if not isinstance(maximum, (int, float)) or not math.isfinite(maximum) or maximum <= .25:
        raise ValueError('radio max_range must be finite and positive')


class RadioSimulation:
    def __init__(self, scene, truth_path=None):
        validate_personnel_route(scene)
        from gz.transport13 import Node
        from gz.msgs10.pose_v_pb2 import Pose_V
        from gz.msgs10.clock_pb2 import Clock
        self.scene = scene
        self.random = random.Random(scene['seed'])
        self.lock = threading.Lock()
        self.poses = {}
        self.time = 0.
        self.start = None
        self.sequence = 0
        self.errors = []
        self.observations = 0
        self.fixes = 0
        self.route_done = False
        self.disabled_nodes = set()
        self.evacuation_paths = None
        self.evacuation_start = None
        self.closure = None
        self.truth_log=truth_path.open('w') if truth_path else None
        self.truth_last=0.
        self.node = Node()
        self.node.subscribe(Pose_V, '/world/mosaic/dynamic_pose/info', self._poses)
        self.node.subscribe(Clock, '/world/mosaic/clock', self._clock)

    def _poses(self, message):
        with self.lock:
            for pose in message.pose:
                if pose.name in {d['id'] for d in self.scene['drones']}:
                    self.poses[pose.name] = [pose.position.x, pose.position.y, pose.position.z]
            if self.truth_log and self.time-self.truth_last>=.1:
                self.truth_log.write(json.dumps(dict(time=self.time,drones=self.poses))+'\n')
                self.truth_last=self.time

    def _clock(self, message):
        self.time = message.sim.sec + message.sim.nsec*1e-9

    def begin(self):
        self.start = self.time

    def evacuate(self, route):
        # Truth stays within the motion/sensor simulator. Join from each actual
        # current position instead of teleporting to the route's first waypoint.
        paths = []
        for index in range(len(self.scene['roster'])):
            position, _ = self._person(index)
            path = [position[:2]]
            for point in route:
                if math.dist(path[-1], point) > 1e-9: path.append(point)
            obstacles = list(self.scene['obstacles']) + ([self.closure] if self.closure else [])
            validate_personnel_route(dict(self.scene, personnel_route=path, obstacles=obstacles))
            paths.append(path)
        self.evacuation_paths = paths
        self.evacuation_start = self.time

    def _person(self, index):
        paths = getattr(self, 'evacuation_paths', None)
        route = paths[index] if paths else self.scene['personnel_route']
        start = self.evacuation_start if paths else self.start
        distance = max(0., self.time-start-index*1.7)*.65
        for a,b in zip(route, route[1:]):
            length = math.dist(a,b)
            if distance <= length:
                return [a[i]+(b[i]-a[i])*distance/length for i in range(2)]+[1.1], False
            distance -= length
        return [*route[-1],1.1], True

    def observe(self, anchors, interference=False):
        if self.start is None: return []
        output = []; completed = []
        with self.lock: poses = dict(self.poses)
        for index, person in enumerate(self.scene['roster']):
            truth, done = self._person(index); completed.append(done)
            ranges = []
            for anchor in anchors:
                if anchor['id'] in self.disabled_nodes: continue
                actual = poses.get(anchor['id'])
                if not actual: continue
                radio = self.scene['radio']
                if math.dist(truth, actual) > radio.get('max_range', math.inf): continue
                walls = sum(crosses(truth, actual, wall) for wall in
                            self.scene['walls'] + ([self.closure['box']] if self.closure else []))
                if self.random.random() < radio['drop_probability']: continue
                sigma = radio['nlos_sigma'] if walls else radio['los_sigma']
                bias = min(walls, 3)*radio['wall_bias']
                if interference and anchor['id'] == anchors[0]['id']: bias += 3.5
                measurement = math.dist(truth, actual) + bias + self.random.gauss(0, sigma)
                estimated = anchor['position']
                ranges.append(dict(id=anchor['id'], x=estimated[0], y=estimated[1], z=estimated[2],
                    distance=max(.05,measurement), sigma=sigma+.06))
            self.sequence += 1; self.observations += 1
            # Evaluation reference is retained inside the sensor/evaluator,
            # separate from the range observation delivered to the solver.
            observation = dict(id=person['id'], sequence=self.sequence, time=self.time, ranges=ranges)
            output.append((observation, truth))
        self.route_done = all(completed)
        return output

    def evaluate(self, estimate, reference):
        if estimate is not None:
            self.fixes += 1
            self.errors.append(math.dist(estimate, reference[:2]))

    def metrics(self):
        errors = sorted(self.errors)
        return dict(samples=self.observations, fixes=self.fixes,
            valid_ratio=self.fixes/self.observations if self.observations else None,
            p95=errors[min(len(errors)-1, math.ceil(len(errors)*.95)-1)] if errors else None,
            maximum=max(errors) if errors else None)

    def close(self):
        self.node.unsubscribe('/world/mosaic/dynamic_pose/info')
        self.node.unsubscribe('/world/mosaic/clock')
        with self.lock:
            if self.truth_log: self.truth_log.close(); self.truth_log=None
