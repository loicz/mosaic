"""Ground task coordination, independent onboard workers and UWB estimates."""
from __future__ import annotations
import copy
import itertools
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import queue
import secrets
import time
from mission_agent import run_agent
from mission_compute import Compute
from mission_coverage import coverage, geometry
from mission_link import CommandLink
from mission_radio import RadioSimulation, validate_personnel_route, validate_evacuation
from mission_sitl import Sitl


def choose_sites(scene):
    """Minimize worst planar geometry over the known mission route, with one loss.

    Candidate positions are map priors, not measured/effective anchors. The UAV
    must still reach, inspect and land before a candidate becomes usable.
    """
    def score(sites):
        return max(geometry([s for s in sites if s['id']!=lost['id']], point)
                   for lost in sites for point in scene['personnel_route'])
    combinations = list(itertools.combinations([s for s in scene['sites'] if not s.get('evacuation_only')],5))
    best = min(combinations,key=score)
    return list(best), score(best)


class Mission:
    def __init__(self, scene, directory, px4, binary, root):
        validate_personnel_route(scene)
        validate_evacuation(scene)
        self.scene=scene; self.directory=directory; self.root=root
        self.partition='mosaic-'+secrets.token_hex(5)
        os.environ['GZ_PARTITION']=self.partition; os.environ['GZ_IP']='127.0.0.1'
        self.sitl=Sitl(scene,directory,px4,self.partition)
        self.compute=Compute(binary,root/'models/mission-lidar.json')
        self.binary=binary; self.children=[]; self.connections={}
        self.transport=CommandLink(self.connections,self.write_record)
        self.telemetry={}; self.visible={}; self.personnel={}; self.visible_people={}
        self.actions=queue.Queue(); self.phase='starting'; self.events=[]
        self.event_sequence=0; self.state={}; self.stopped=False
        self.selected,self.geometry=choose_sites(scene)
        self.assignments=[]; self.commanded=set(); self.recalled=set()
        self.link_until=0.; self.interference=False; self.failed=None
        self.last_radio=0.; self.last_record=0.; self.last_snapshot=0.; self.failure_time=None
        self.recovery_time=None; self.disconnection_records=[]; self.link_start=None
        self.arrival_since=None; self.outcome=None
        self.anchor_sites={}; self.anchor_seen={}; self.recovery_since=None
        self.anchor_expected_since={}
        self.replacement=None; self.replacement_complete=False
        self.observation_sequences={}
        self.route_blocked=False; self.exit_plan=None; self.exit_since=None
        self.handover_since=None; self.reposition=None; self.coverage_report=None
        self.coverage_status='awaiting_request'; self.evacuation_time=None
        self.token=secrets.token_urlsafe(24)
        self.record=(directory/'session.jsonl').open('w')
        self.ranges=(directory/'ranges.jsonl').open('w')
        self.radio=None
        self.write_record('manifest',dict(schema='mosaic.mission.record.v1',scene=scene,
             simulation='Gazebo 8 / PX4 v1.17.0',model='lidar-corridor-4103-v1'))

    def write_record(self,kind,value):
        self.record.write(json.dumps(dict(kind=kind,value=value),ensure_ascii=False,allow_nan=False)+'\n')
        self.record.flush()

    def event(self,code,text):
        self.event_sequence+=1
        event=dict(sequence=self.event_sequence,time=self.radio.time if self.radio else 0,code=code,text=text)
        self.events.append(event); self.events=self.events[-100:]
        self.write_record('event',event)

    def start(self):
        self.sitl.start_world(); self.radio=RadioSimulation(self.scene,self.directory/'physics-truth.jsonl')
        prior={key:self.scene[key] for key in ('walls','bounds','flight_height')}
        for index,drone in enumerate(self.scene['drones']):
            parent,child=mp.Pipe()
            process=mp.Process(target=run_agent,args=(index,drone,prior,child,self.binary,self.root/'models/mission-lidar.json',self.directory/(drone['id']+'-onboard.jsonl')))
            process.start(); child.close()
            self.children.append(process); self.connections[drone['id']]=parent
        self.sitl.start_flight_controllers()
        self.event('boot','Flight controllers and onboard processors starting.')

    def send(self,identity,message):
        return self.transport.send(identity,message,self.radio.time)

    def handle(self,action):
        op=action.get('op'); now=self.radio.time
        link=now>=self.link_until
        if op=='disconnect' and link:
            self.link_start=now; self.link_until=now+25
            self.transport.resume_at=self.link_until
            self.event('link_lost','Command link lost. Onboard missions continue.')
        elif op=='reconnect':
            self.link_until=now
            self.transport.resume_at=now
        elif op=='interference':
            self.interference=not self.interference
            self.event('interference','Single-link ranging interference enabled.' if self.interference else 'Ranging interference cleared.')
        elif op=='fail_anchor' and self.failed is None and not self.radio.disabled_nodes:
            anchors=[d for d in self.telemetry.values() if d.get('anchor')]
            if anchors:
                # Out-of-band simulator fault; the coordinator discovers the
                # identity from missing sensor packets, just as for unknown loss.
                identity=anchors[0]['id']; self.radio.disabled_nodes.add(identity)
                self.event('anchor_fault_injected',f'{identity} ranging output disabled.')
        elif not link:
            self.event('command_rejected','Command link unavailable. Command was not sent.')
        elif op=='deploy' and self.phase=='idle':
            available=list(self.scene['drones'])
            # Mission assignment minimizes known-map travel distance. Interior
            # obstacles are discovered only by the individual flight workers.
            for site in self.selected:
                drone=min(available,key=lambda d:math.dist(d['dock'],site['position']))
                available.remove(drone); self.assignments.append((drone['id'],site))
            self.phase='deploying'; self.event('deploy','Autonomous deployment started. Sensing, placement, and calibration in progress.')
        elif op=='task' and self.phase=='ready':
            self.phase='tracking'; self.radio.begin(); self.event('task','Personnel entered. Position and trail recording started.')
            self.anchor_seen={identity:now for identity in self.anchor_sites}
        elif op=='block_route' and self.phase=='objective_complete' and not self.route_blocked:
            if any(d['state'] in ('takeoff','transit','landing','calibrating') for d in self.telemetry.values()):
                self.event('command_rejected','Passage closure requires all aircraft to be stationary.')
            elif self.sitl.block_passage(self.scene['evacuation']['closure']):
                self.route_blocked=True
                self.radio.closure=self.scene['evacuation']['closure']
                # This operator-declared closure is an explicit route constraint,
                # not a hidden obstacle inferred from simulator truth. Each UAV
                # retains it locally and still plans with its own lidar/odometry.
                for drone in self.scene['drones']:
                    self.send(drone['id'],dict(op='avoid_area',box=self.scene['evacuation']['closure']['box']))
                self.event('route_blocked','East passage closed. West detour and alternate assembly area required.')
            else:
                self.event('command_rejected','Passage closure was not acknowledged by the simulator.')
        elif op=='evacuate' and self.phase=='objective_complete':
            name='alternate' if self.route_blocked else 'primary'
            self.exit_plan=dict(self.scene['evacuation'][name],name=name)
            self.phase='planning_evacuation'; self.coverage_status='checking'
            self.event('evacuation_requested',f'Evacuation requested via {self.exit_plan["label"]}. Personnel hold at the objective while coverage is checked.')
            self.write_record('evacuation_plan',dict(time=now,**self.exit_plan))
        elif op=='recall' and self.phase in ('ready','evacuated'):
            self.outcome='objective_completed' if self.phase=='evacuated' else 'cancelled_before_entry'
            self.phase='recalling'; self.event('recall','Recovering nodes sequentially to the launch area.')
        elif op=='recall' and self.radio.start is not None:
            self.event('recall_rejected','Personnel have not completed evacuation. Positioning nodes remain on site.')
        else:
            self.event('command_rejected','Command unavailable in this phase.')

    def fresh_people(self, now):
        return (set(self.personnel)=={p['id'] for p in self.scene['roster']} and
                all(p['status']=='current' and 0<=now-p['time']<=.4 for p in self.personnel.values()))

    def plan_evacuation(self, now, link, moving):
        """Keep the cooperative simulation roster at the objective until handover.

        A spare is preferred. With no spare, only a dispensable healthy anchor
        may move: fresh fixes and remaining geometry must support everyone now.
        Candidate coverage never enables departure; measured anchors must pass.
        """
        route=self.exit_plan['route']; maximum=self.scene['radio']['max_range']
        anchors=[a for i,a in self.anchor_sites.items() if 0<=now-self.anchor_seen.get(i,-math.inf)<=.4]
        self.coverage_report=coverage(anchors,route,maximum)
        fresh=self.fresh_people(now)
        new_used=(self.reposition is None or
                  self.reposition.get('complete') and any(self.reposition['id'] in p['used'] for p in self.personnel.values()))
        if self.coverage_report['covered'] and fresh and link and not moving and new_used:
            if self.handover_since is None: self.handover_since=now
            self.coverage_status='verifying'
            if now-self.handover_since>=2:
                self.radio.evacuate(route)
                self.phase='evacuating'; self.coverage_status='ready'
                self.event('coverage_ready','Measured anchors and fresh personnel fixes verified. Evacuation may proceed.')
                self.event('evacuation_started','Personnel withdrawing; positioning and trail recording remain active.')
            return
        self.handover_since=None
        if moving:
            self.coverage_status='positioning'; return
        if not fresh or not link:
            self.coverage_status='waiting_for_observations'; return
        # One relocation per reference evacuation. A failed/unusable arrival
        # stays visibly blocked rather than oscillating between candidate sites.
        if self.reposition:
            self.coverage_status='coverage_unavailable'; return
        occupied={site['id'] for _,site in self.assignments}
        candidates=[s for s in self.scene['sites'] if s['id'] not in occupied]
        spare=next((d['id'] for d in self.scene['drones'] if d['id'] not in self.commanded),None)
        choices=[]
        for site in candidates:
            if spare:
                report=coverage(anchors+[site],route,maximum)
                if report['covered']: choices.append((report['worst_geometry'],spare,site,'deploy'))
            else:
                for anchor in anchors:
                    identity=anchor['id']
                    if self.telemetry[identity]['state']!='anchor': continue
                    remaining=[a for a in anchors if a['id']!=identity]
                    # Use actual accepted ranging sets as well as geometry.
                    if not all(len(set(p['used'])-{identity})>=3 and
                               coverage(remaining,[p['position']],maximum)['covered']
                               for p in self.personnel.values()): continue
                    report=coverage(remaining+[site],route,maximum)
                    if report['covered']: choices.append((report['worst_geometry'],identity,site,'relocate'))
        if not choices:
            if self.coverage_status!='coverage_unavailable':
                self.event('coverage_unavailable','No feasible coverage handover. Personnel remain at the objective; fleet recall stays locked.')
            self.coverage_status='coverage_unavailable'; return
        _,identity,site,op=min(choices,key=lambda v:(v[0],v[1],v[2]['id']))
        if not self.send(identity,dict(op=op,site=site)): return
        self.reposition=dict(id=identity,site=site['id'],op=op,complete=False)
        self.commanded.add(identity)
        self.assignments=[(i,s) for i,s in self.assignments if i!=identity]+[(identity,site)]
        self.anchor_sites.pop(identity,None); self.anchor_seen.pop(identity,None)
        self.telemetry[identity]['state']='takeoff'; self.coverage_status='positioning'
        self.event('coverage_dispatched',f'{identity} moving to {site["id"]} for evacuation coverage. Remaining nodes continue tracking everyone.')
        self.write_record('coverage_handover',dict(time=now,id=identity,site=site,op=op,
                          people=copy.deepcopy(self.personnel),remaining=[a for a in anchors if a['id']!=identity]))

    def tick(self):
        now=self.radio.time
        link=now>=self.link_until
        for identity,message in self.transport.receive(now):
            previous=self.telemetry.get(identity)
            self.telemetry[identity]=message
            self.visible[identity]=copy.deepcopy(message)
            relocation_matches=(not self.reposition or identity!=self.reposition['id'] or
                                (message.get('target') or {}).get('id')==self.reposition['site'])
            if message.get('anchor') and identity!=self.failed and relocation_matches:
                self.anchor_sites[identity]=dict(id=identity,position=message['anchor'])
                self.anchor_seen.setdefault(identity,now)
            else:
                self.anchor_sites.pop(identity,None)
            if previous and previous['state']!=message['state']:
                self.event('drone_state',f'{identity} / {message["state"]}')
            if identity==self.replacement and message['state']=='anchor' and not self.replacement_complete:
                self.replacement_complete=True
                self.event('replacement_complete',f'{identity} replacement perched and calibrated.')
            if (self.reposition and identity==self.reposition['id'] and relocation_matches and
                message.get('anchor') and not self.reposition['complete']):
                self.reposition['complete']=True
                self.event('coverage_perched',f'{identity} perched at {self.reposition["site"]}. Checking new ranging before departure.')
        if self.link_start is not None and link:
            self.disconnection_records.append(dict(start=self.link_start,end=now))
            self.link_start=None; self.event('link_restored','Link restored. Onboard progress synchronized.')
            self.visible=copy.deepcopy(self.telemetry)
        while not self.actions.empty(): self.handle(self.actions.get_nowait())
        link=now>=self.link_until
        if self.phase=='starting' and len(self.telemetry)==len(self.scene['drones']) and all(d['state']=='idle' for d in self.telemetry.values()):
            self.phase='idle'; self.event('ready_to_deploy','Fleet ready. Autonomous deployment available.')
        moving=any(d['state'] in ('takeoff','transit','landing','calibrating') for d in self.telemetry.values())
        if self.phase=='deploying' and link and not moving:
            pending=[a for a in self.assignments if a[0] not in self.commanded]
            if pending:
                identity,site=pending[0]; self.send(identity,dict(op='deploy',site=site)); self.commanded.add(identity)
                # Do not schedule a second UAV before first command is acknowledged.
                self.telemetry[identity]['state']='takeoff'
            elif all(self.telemetry[i]['state']=='anchor' for i,_ in self.assignments):
                self.phase='ready'; self.event('network_ready','Positioning network ready. Personnel may enter.')
        # Calibrated, stationary coordinates survive command-link loss. UWB is
        # a separate sensor channel; only its actual packets establish health.
        anchors=list(self.anchor_sites.values())
        if self.failed and self.phase in ('tracking','objective_complete','ready','planning_evacuation','evacuating') and link and not moving:
            spare=next((d for d in self.scene['drones'] if d['id'] not in self.commanded),None)
            if spare:
                # Failed aircraft still occupies its perch: use a different site.
                alternative=next(s for s in self.scene['sites'] if not s.get('evacuation_only') and s['id'] not in {v['id'] for _,v in self.assignments})
                self.send(spare['id'],dict(op='deploy',site=alternative)); self.commanded.add(spare['id'])
                self.assignments.append((spare['id'],alternative)); self.telemetry[spare['id']]['state']='takeoff'
                self.replacement=spare['id']
                self.event('replacement_dispatched',f'{spare["id"]} dispatched to the reserve anchor site.')
                moving=True
        if self.phase=='recalling' and link and not moving:
            pending=[i for i in self.commanded if i not in self.recalled and self.telemetry[i]['state'] in ('anchor','radio_failed')]
            if pending:
                identity=sorted(pending)[0]; self.send(identity,dict(op='recall')); self.recalled.add(identity)
                self.telemetry[identity]['state']='takeoff'
                self.anchor_sites.pop(identity,None)
            elif self.recalled==self.commanded and all(self.telemetry[i]['state']=='returned' for i in self.commanded):
                self.phase='complete'; self.event('complete','All deployed nodes returned. No nodes remain on site.')
        if self.radio.start is not None and self.phase in ('tracking','objective_complete','planning_evacuation','evacuating','evacuated') and now-self.last_radio>=.2:
            self.last_radio=now
            for observation,reference in self.radio.observe(anchors,self.interference):
                # The simulator clock advances on another thread while observe
                # generates packets. Compare with receipt time, not tick entry.
                now=self.radio.time
                identity=observation['id']; stamp=observation['time']; sequence=observation['sequence']
                if (identity not in {p['id'] for p in self.scene['roster']} or
                    not 0<=now-stamp<=.4 or sequence<=self.observation_sequences.get(identity,-1)):
                    self.write_record('observation_rejected',dict(id=identity,time=now,sequence=sequence))
                    continue
                self.observation_sequences[identity]=sequence
                for measurement in observation['ranges']:
                    if measurement['id'] in self.anchor_sites:
                        self.anchor_seen[measurement['id']]=stamp
                previous=self.personnel.get(identity)
                prior=previous['position'] if previous else None
                result=self.compute.call(op='locate',ranges=observation['ranges'],height=1.1,prior=prior)
                position=result.get('position')
                self.radio.evaluate(position,reference)
                trail=previous['trail'] if previous else []
                if position:
                    # A new fix cannot establish a traversed path across missing
                    # observations. Keep the gap in recorded and live trails.
                    if previous and (previous['status']!='current' or stamp-previous['time']>.4+1e-8):
                        trail=trail+[None]
                    trail=(trail+[position])[-3000:]
                self.personnel[identity]=dict(id=identity,time=stamp,sequence=sequence,position=position or prior,
                    status='current' if position else 'uncertain',allowance=result.get('allowance'),
                    used=result.get('used',[]),rejected=result.get('rejected',[]),trail=trail)
                self.ranges.write(json.dumps(dict(observation=observation,prior=prior,result=result,reference=reference),allow_nan=False)+'\n')
            self.ranges.flush()
            # A single absent node alongside live peers is distinguishable from
            # a receiver-wide outage. Never diagnose all anchors from silence.
            # With bounded radio range, absence is only a node-failure signal
            # while a freshly located tag should be reachable. Leaving coverage
            # is not a broken radio, and re-entering starts a new timeout window.
            expected={i for i,a in self.anchor_sites.items() if any(
                p['status']=='current' and 0<=now-p['time']<=.4 and
                math.dist(p['position'],a['position'][:2]) <=
                    self.scene['radio']['max_range']-max(.75,p.get('allowance') or .75)
                for p in self.personnel.values())}
            self.anchor_expected_since={i:self.anchor_expected_since.get(i,now) for i in expected}
            missing=[i for i in expected if now-max(self.anchor_seen[i],self.anchor_expected_since[i])>=1.2]
            peers=[i for i in self.anchor_sites if now-self.anchor_seen[i]<=.4]
            if self.failed is None and len(missing)==1 and len(peers)>=3:
                self.failed=missing[0]; self.failure_time=now
                self.anchor_sites.pop(self.failed,None)
                self.event('anchor_failed',f'{self.failed} ranging timed out. The anchor was excluded and a replacement scheduled.')
        for person in self.personnel.values():
            if now-person['time']>.4:
                person['status']='last_known' if now-person['time']>1.5 else 'uncertain'
        if self.radio.start is not None:
            fresh=self.fresh_people(now)
            if self.failure_time is not None and self.recovery_time is None:
                if not fresh: self.recovery_since=None
                elif self.recovery_since is None: self.recovery_since=now
                elif now-self.recovery_since>=5:
                    self.recovery_time=self.recovery_since-self.failure_time
                    self.event('service_restored','Fresh fixes sustained for all personnel for 5 s. Replacement continues.')
            # Arrival is determined from fresh solved positions, never from the
            # simulator's hidden route progress or personnel ground truth.
            arrived=fresh and all(
                math.dist(p['position'],self.scene['destination']['position'])<.9
                for p in self.personnel.values())
            if not arrived: self.arrival_since=None
            elif self.arrival_since is None: self.arrival_since=now
            if self.arrival_since is not None and now-self.arrival_since>2 and self.phase=='tracking':
                self.phase='objective_complete'; self.event('objective','Personnel reached the indoor objective. Evacuation is still required.')
            if self.phase=='planning_evacuation': self.plan_evacuation(now,link,moving)
            if self.phase=='evacuating':
                safe=fresh and all(math.dist(p['position'],self.exit_plan['route'][-1])<.9 for p in self.personnel.values())
                if not safe: self.exit_since=None
                elif self.exit_since is None: self.exit_since=now
                if self.exit_since is not None and now-self.exit_since>=2:
                    self.phase='evacuated'; self.evacuation_time=now
                    self.event('personnel_evacuated','Every enrolled person has fresh fixes in the outdoor assembly area for 2s. Fleet recovery is now available.')
        if link and self.personnel: self.visible_people=copy.deepcopy(self.personnel)
        public_scene={key:self.scene[key] for key in ('id','title','bounds','walls','sites','drones','roster','destination','evacuation')}
        drones=[]
        for drone in self.scene['drones']:
            value=copy.deepcopy(self.visible.get(drone['id'],dict(id=drone['id'],state='boot',time=0,position=None)))
            value['age']=max(0.,now-value['time']); value['stale']=value['age']>1.5
            if drone['id']==self.failed:
                value['anchor']=None
                if value['state']=='anchor': value['state']='radio_failed'
            drones.append(value)
        people=copy.deepcopy(list(self.visible_people.values()))
        for person in people:
            person['age']=max(0.,now-person['time'])
            if person['age']>1.5: person['status']='last_known'
        self.state=dict(schema='mosaic.mission.state.v1',time=now,phase=self.phase,
            scene=public_scene,drones=drones,people=people,events=self.events[-12:],link=link,
            reconnect_in=max(0.,self.link_until-now),interference=self.interference,failed=self.failed,
            active_anchors=sum(bool(d.get('anchor')) and not d['stale'] for d in drones),
            selected_sites=[s['id'] for s in self.selected],geometry=self.geometry,
            evacuation=dict(plan=self.exit_plan,blocked=self.route_blocked,status=self.coverage_status,
                            coverage=self.coverage_report,reposition=self.reposition,completed_at=self.evacuation_time),
            token=self.token,evidence='PX4 + Gazebo software-in-the-loop',recording=True,outcome=self.outcome)
        if time.monotonic()-self.last_snapshot>.2:
            self.last_snapshot=time.monotonic(); recorded={k:v for k,v in self.state.items() if k!='token'}
            self.write_record('state',recorded)
        for process in self.children:
            if process.exitcode is not None: raise RuntimeError('onboard worker stopped unexpectedly')

    def close(self):
        # tick() throttles snapshots, but the launcher may exit immediately on
        # completion. Preserve the latest state before stopping its producers.
        if self.state:
            self.write_record('state',{k:v for k,v in self.state.items() if k!='token'})
        for connection in self.connections.values():
            try: connection.send({'op':'stop'})
            except (BrokenPipeError,EOFError): pass
        for process in self.children:
            process.join(3)
            if process.is_alive(): process.terminate(); process.join(2)
        for connection in self.connections.values(): connection.close()
        self.sitl.close(); self.compute.close()
        if self.radio: self.radio.close()
        metrics=dict(positioning=self.radio.metrics() if self.radio else {},recovery_seconds=self.recovery_time,
                     disconnections=self.disconnection_records,phase=self.phase)
        (self.directory/'metrics.json').write_text(json.dumps(metrics,indent=2))
        self.record.close(); self.ranges.close()
