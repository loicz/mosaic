"""One virtual onboard computer per UAV. No world truth or ground imagery input.

Inputs: prior floor map, task messages, that UAV's PX4 telemetry and Gazebo lidar.
Outputs: MAVLink setpoints and bounded telemetry. Ground disconnection does not
terminate this process or its flight-control connection.
"""
from __future__ import annotations
import math
import time
from pathlib import Path
from mission_compute import Compute
from mission_mapping import LidarMap


def run_agent(index, drone, prior, connection, binary, model, journal_path=None):
    from gz.transport13 import Node
    from gz.msgs10.laserscan_pb2 import LaserScan
    from gz.msgs10.clock_pb2 import Clock
    from pymavlink import mavutil
    node = Node()
    sensors = {'scan': None, 'clock': 0.0}
    position = None; yaw = 0.; last_position = -math.inf
    def scan(message):
        # Only ranges and angles cross the sensor boundary, never world_pose.
        sensors['scan'] = (list(message.ranges), message.angle_min, message.angle_step,
                          sensors['clock'], position.copy() if position else None, yaw, last_position)
    def clock(message):
        sensors['clock'] = message.sim.sec + message.sim.nsec * 1e-9
    node.subscribe(LaserScan, f'/mosaic/{drone["id"]}/scan', scan)
    node.subscribe(Clock, '/world/mosaic/clock', clock)
    mav = mavutil.mavlink_connection(f'udpin:127.0.0.1:{14540+index}', source_system=240+index)
    compute = Compute(Path(binary), Path(model))
    identity = index+1
    state = 'boot'; target = None; position = None; velocity = [0., 0., 0.]
    yaw = 0.; armed = False; landed = True; heartbeat = 0.; telemetry = 0.
    last_position = -math.inf; path = []; path_index = 1
    local_map = LidarMap(prior['walls'], drone['dock']); cells = local_map.cells
    last_plan = -math.inf; last_infer = -math.inf; last_command = -math.inf
    phase_time = 0.; returning = False; radio_ok = True; scans = 0; inferences = 0
    decisions = 0; risk = [1., 0., 0.]; last_error = ''; samples = []; calibrated = None
    setpoint = None; ready_since = None; start_wall = time.monotonic()
    hold_reason = None
    route_exclusions = []
    flight_height = prior['flight_height']; dock = drone['dock']
    journal=Path(journal_path).open('w') if journal_path else None
    journal_time=-math.inf

    def command(code, *params):
        mav.mav.command_long_send(identity, 1, code, 0, *(list(params)+[0.]*(7-len(params))))

    def change(next_state):
        nonlocal state, phase_time, last_command
        state = next_state; phase_time = sensors['clock']; last_command = -math.inf

    def plan():
        nonlocal path, path_index, last_plan, last_error
        obstacles = prior['walls'] + [[x*.4-.2, y*.4-.2, .4, .4] for x, y in cells]
        result = compute.call(op='plan', **{'from': position[:2], 'to': target['position'],
             'minimum': prior['bounds'][0], 'maximum': prior['bounds'][1],
             'obstacles': obstacles, 'cell': .25, 'clearance': .58,
             'escape_clearance': .35})
        path = result['path']; path_index = 1; last_plan = sensors['clock']
        last_error = '' if path else 'Path temporarily blocked. Waiting for local replanning.'

    try:
        while True:
            now = sensors['clock']; wall = time.monotonic()
            while connection.poll():
                message = connection.recv()
                if message['op'] == 'stop': return
                if message['op'] == 'avoid_area':
                    box = message['box']
                    if box not in route_exclusions:
                        route_exclusions.append(box)
                        prior['walls'].append(box)
                        last_plan = -math.inf
                if ((message['op'] == 'deploy' and state in ('idle', 'returned')) or
                    (message['op'] == 'relocate' and state == 'anchor')):
                    target = message['site']; returning = False; calibrated = None; samples = []
                    change('takeoff'); setpoint = [*position[:2], flight_height] if position else None
                elif message['op'] == 'recall' and state in ('anchor', 'radio_failed'):
                    target = {'id': 'dock', 'position': dock}; returning = True; calibrated = None
                    change('takeoff'); setpoint = [*position[:2], flight_height]
                elif message['op'] == 'radio_failure':
                    radio_ok = False
                    if state == 'anchor': change('radio_failed')
            while True:
                msg = mav.recv_match(blocking=False)
                if msg is None: break
                kind = msg.get_type()
                if kind == 'HEARTBEAT': armed = bool(msg.base_mode & 128); heartbeat = wall
                elif kind == 'LOCAL_POSITION_NED':
                    position = [msg.y, msg.x, -msg.z]; velocity = [msg.vy, msg.vx, -msg.vz]; last_position = now
                elif kind == 'ATTITUDE': yaw = math.pi/2-msg.yaw
                elif kind == 'EXTENDED_SYS_STATE': landed = msg.landed_state == 1
                elif kind == 'STATUSTEXT' and msg.severity <= 4: last_error = msg.text
            if wall - telemetry > .2:
                telemetry = wall
                report=dict(id=drone['id'], state=state, time=now, position=position,
                    armed=armed, target=target, path=path, discovered=len(cells), scans=scans,
                    inferences=inferences, decisions=decisions, risk=risk,
                    anchor=calibrated if radio_ok and state == 'anchor' else None,
                    radio_ok=radio_ok, error=last_error,
                    route_exclusions=route_exclusions,
                    sensor_age=now-sensors['scan'][3] if sensors['scan'] else None,
                    px4_connected=wall-heartbeat < 3, runtime=wall-start_wall)
                connection.send(report)
                if journal and now-journal_time>=.5:
                    import json
                    journal.write(json.dumps(report,allow_nan=False)+'\n'); journal.flush(); journal_time=now
            if not position or wall-heartbeat > 3:
                time.sleep(.03); continue
            # This heartbeat is the onboard computer's link to its own FCU.
            mav.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_ONBOARD_CONTROLLER,
                                   mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 4)
            if state == 'boot' and now-last_position < .5 and sensors['scan']:
                if ready_since is None: ready_since = now
                if now-ready_since > 5: change('idle')
            if state in ('takeoff', 'transit', 'landing'):
                if state == 'takeoff':
                    setpoint = [*position[:2], flight_height] if setpoint is None else setpoint
                    if now-phase_time > 2 and now-last_command > 2 and not armed:
                        command(mavutil.mavlink.MAV_CMD_DO_SET_MODE, 1, 6)
                        command(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1)
                        last_command = now
                    if armed and abs(position[2]-flight_height) < .2:
                        plan(); change('transit')
                elif state == 'transit':
                    sample = sensors['scan']
                    # Stop immediately on stale sensing, never advance blindly.
                    if sample is None or now-sample[3] > .8 or now-last_position > .6:
                        if hold_reason != 'sensors': setpoint = position.copy()
                        hold_reason = 'sensors'; last_error = 'Onboard sensor timeout. Holding position.'
                    else:
                        ranges, angle_min, angle_step, stamp = sample[:4]
                        changed = local_map.update(sample)
                        if hold_reason == 'sensors' or now-last_plan > 2 or changed and now-last_plan > .5:
                            plan()
                            if changed: decisions += 1
                        if not path:
                            # Mapping continues above even without a route.
                            # Hold a fixed point until fresh free-space evidence
                            # makes a route available again.
                            if hold_reason != 'path': setpoint = position.copy()
                            hold_reason = 'path'
                        else:
                            hold_reason = None
                            while path_index < len(path)-1 and math.dist(position[:2], path[path_index]) < .15:
                                path_index += 1
                            waypoint = path[path_index]
                            direction = math.atan2(waypoint[1]-position[1], waypoint[0]-position[0])
                            if now-last_infer > .18:
                                last_infer = now; scans += 1
                                feature = []
                                for i in range(9):
                                    relative = (direction-yaw-.55+1.1*i/8+math.pi) % (2*math.pi)-math.pi
                                    j = max(0, min(len(ranges)-1, round((relative-angle_min)/angle_step)))
                                    value = ranges[j]
                                    feature.append((min(8., max(0., value)) if math.isfinite(value) else (0. if value < 0 else 8.))/4-1)
                                risk = compute.call(op='infer', input=feature)['probabilities']; inferences += 1
                            if path:
                                waypoint = path[min(path_index, len(path)-1)]
                                gap = math.dist(position[:2], waypoint)
                                horizon = .65 if risk[1]+risk[2] > .45 else 1.6
                                factor = min(1., horizon/max(gap, .001))
                                setpoint = [position[i]+(waypoint[i]-position[i])*factor for i in range(2)]+[flight_height]
                            if math.dist(position[:2], target['position']) < .25 and math.hypot(*velocity[:2]) < .35:
                                change('landing')
                elif state == 'landing':
                    # PX4 performs actual descent and detects physical support contact.
                    if now-last_command > 2 and armed:
                        command(mavutil.mavlink.MAV_CMD_NAV_LAND, 0, 0, 0, math.nan, math.nan, math.nan, math.nan)
                        last_command = now
                    if not armed and now-phase_time > 2:
                        if math.dist(position[:2],target['position'])>.65:
                            last_error='Unable to stabilize at the target perch. Redeployment required.'; change('perch_rejected')
                        elif returning: change('returned')
                        elif not .3<position[2]<.7:
                            last_error='Perch height is outside the support interface tolerance. Anchor remains disabled.'; change('perch_rejected')
                        else: change('calibrating'); samples = []
                if setpoint is not None and state != 'landing':
                    mav.mav.set_position_target_local_ned_send(0, identity, 1,
                        mavutil.mavlink.MAV_FRAME_LOCAL_NED, 0b110111111000,
                        setpoint[1], setpoint[0], -setpoint[2], 0,0,0,0,0,0,0,0)
            elif state == 'calibrating':
                samples.append(position.copy())
                if now-phase_time >= 2:
                    calibrated = [sum(p[i] for p in samples)/len(samples) for i in range(3)]
                    change('anchor' if radio_ok else 'radio_failed')
            time.sleep(.045)
    except (EOFError, BrokenPipeError, ConnectionResetError):
        pass
    finally:
        if journal: journal.close()
        compute.close(); mav.close(); connection.close()
