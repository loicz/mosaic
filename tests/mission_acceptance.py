"""MA-1 run-level independent checks. Passing this does NOT pass all A01-A13."""
import argparse,json,math,sys,bisect
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from mission_compute import Compute
def read(p):
    with p.open() as f:return [json.loads(x) for x in f if x.strip()]
def p95(v):
    return sorted(v)[math.ceil(len(v)*.95)-1] if v else None
def crosses(a,b,box):
    t0,t1=0.,1.
    for i in range(2):
        low,hi=box[i],box[i]+box[i+2];delta=b[i]-a[i]
        if abs(delta)<1e-12:
            if not low<=a[i]<=hi:return False
        else:
            x,y=sorted(((low-a[i])/delta,(hi-a[i])/delta));t0=max(t0,x);t1=min(t1,y)
            if t0>t1:return False
    return True
def check_run(directory,binary,scenario):
    required_faults=scenario in ('default','offline','unknown')
    checks={};detail={}
    def check(name,condition,value=None):
        checks[name]='PASS' if condition else 'FAIL'
        if value is not None:detail[name]=value
    try:
        session=read(directory/'session.jsonl');states=[x['value'] for x in session if x['kind']=='state'];events=[x['value'] for x in session if x['kind']=='event']
        scene=next(x['value']['scene'] for x in session if x['kind']=='manifest');roster=[x['id'] for x in scene['roster']]
        rows=read(directory/'ranges.jsonl');truth=read(directory/'physics-truth.jsonl');summary=json.loads((directory/'metrics.json').read_text())
        journals={x['id']:read(directory/(x['id']+'-onboard.jsonl')) for x in scene['drones']}
        check('required_nonempty_logs',bool(states and rows and truth) and all(journals.values()))
        if not states or not rows or not truth or not all(journals.values()):return dict(passed=False,checks=checks,details=detail)
        check('terminal_complete',states[-1]['phase']=='complete' and states[-1]['outcome']=='objective_completed')
        check('zero_initial_nodes',states[0]['active_anchors']==0)
        check('zero_final_nodes_disarmed',states[-1]['active_anchors']==0 and all(not d.get('armed') and d['state'] in ('idle','returned') for d in states[-1]['drones']))
        check('fixed_roster',set(x['observation']['id'] for x in rows)==set(roster))
        check('unique_observation_sequences',len({x['observation']['sequence'] for x in rows})==len(rows))
        # Independently check the simulated personnel, not just aircraft or
        # errors relative to a potentially impossible reference trajectory.
        clearance=scene.get('personnel_clearance',.3)
        boxes=[(x-clearance,y-clearance,w+2*clearance,h+2*clearance)
               for x,y,w,h in scene['walls']+[o['box'] for o in scene.get('obstacles',[])]]
        def clear_motion(a,b):
            return (all(math.isfinite(p[i]) and scene['bounds'][0][i]+clearance<p[i]<scene['bounds'][1][i]-clearance
                        for p in (a,b) for i in range(2)) and not any(crosses(a,b,box) for box in boxes))
        route=scene['personnel_route']
        check('personnel_route_clearance',math.isfinite(clearance) and clearance>0 and len(route)>=2 and
              all(math.dist(a,b)>0 and clear_motion(a,b) for a,b in zip(route,route[1:])))
        personnel_collisions=[];previous_references={}
        for row in rows:
            identity=row['observation']['id'];position=row['reference']
            previous=previous_references.get(identity,position)
            if not clear_motion(previous,position):
                personnel_collisions.append(dict(id=identity,time=row['observation']['time'],position=position))
            previous_references[identity]=position
        check('personnel_motion_clearance',not personnel_collisions,personnel_collisions[:20])
        tasks=[e['time'] for e in events if e['code']=='task'];objectives=[e['time'] for e in events if e['code']=='objective']
        check('task_and_objective_exist',len(tasks)==1 and len(objectives)==1)
        if not tasks or not objectives:return dict(passed=False,checks=checks,details=detail)
        start,objective_end=tasks[0],objectives[0]
        evacuation=scene.get('evacuation')
        withdrawals=[e['time'] for e in events if e['code']=='evacuation_started']
        exits=[e['time'] for e in events if e['code']=='personnel_evacuated']
        recalls=[e['time'] for e in events if e['code']=='recall']
        end=exits[0] if evacuation and exits else objective_end
        failures=[e for e in events if e['code']=='anchor_failed'];lost=[e for e in events if e['code']=='link_lost'];restored=[e for e in events if e['code']=='link_restored']
        if scenario=='baseline':check('baseline_has_no_anchor_failure',not failures,failures)
        closures=[e['time'] for e in events if e['code']=='route_blocked']
        if evacuation:
            check('evacuation_before_recovery',len(withdrawals)==len(exits)==len(recalls)==1 and
                  objective_end<withdrawals[0]<exits[0]<=recalls[0])
            fleet_recalls=[r['value']['time'] for r in session if r['kind']=='onboard_command' and r['value']['command']['op']=='recall']
            check('no_aircraft_recalled_before_roster_exit',bool(exits and fleet_recalls) and all(t>=exits[0] for t in fleet_recalls))
            if closures:
                box=evacuation['closure']['box'];x,y,w,h=box
                check('declared_closure_retained_on_every_aircraft',all(any(
                      closures[0]<=r['time']<recalls[0] and box in r.get('route_exclusions',[])
                      for r in journal) for journal in journals.values()) if recalls else False)
                expanded=(x-clearance,y-clearance,w+2*clearance,h+2*clearance)
                prior={};collisions=[]
                for r in rows:
                    identity=r['observation']['id'];t=r['observation']['time'];p=r['reference']
                    if t>=closures[0] and crosses(prior.get(identity,p),p,expanded):collisions.append((identity,t))
                    prior[identity]=p
                check('personnel_avoid_new_closure',not collisions,collisions[:20])
        if required_faults:
            check('required_faults_present',bool(failures and lost and restored),{'anchor_failed':failures,'link_lost':lost,'link_restored':restored})
        if lost:
            durations=[next((e['time']-x['time'] for e in restored if e['time']>=x['time']),-1) for x in lost]
            check('link_outage_25_sim_seconds',all(v>=25-1e-8 for v in durations),durations)
            intervals=[(e['time'],e['time']+duration) for e,duration in zip(lost,durations) if duration>=0]
            stale=[s for s in states if not s['link'] and any(a+1.5<s['time']<=b for a,b in intervals)]
            check('ground_stale_after_1_5s',bool(stale) and all(all(d['stale'] or d['age']<=1.5 for d in s['drones']) and all(p['status']!='current' or p['age']<=1.5 for p in s['people']) for s in stale))
            drops=[r['value'] for r in session if r['kind']=='transport_drop' and r['value']['direction']=='telemetry']
            received=[r['value'] for r in session if r['kind']=='transport_receive']
            commands=[r['value'] for r in session if r['kind']=='onboard_command']
            # A tick can receive a packet, then handle disconnect without the
            # simulation clock advancing. Journal order disambiguates that
            # boundary; a pre-disconnect delivery is not an outage violation.
            loss_offsets=[i for i,r in enumerate(session) if r['kind']=='event' and r['value']['code']=='link_lost']
            blocked_deliveries=[r['value'] for i,r in enumerate(session) if r['kind']=='transport_receive'
                                and any(i>offset and a<=r['value']['time']<b
                                        for offset,(a,b) in zip(loss_offsets,intervals))]
            check('telemetry_actually_dropped',all(any(a<=r['time']<b for r in drops) for a,b in intervals))
            check('no_ground_delivery_during_loss',bool(received) and not blocked_deliveries,blocked_deliveries[:20])
            check('no_command_delivery_during_loss',not any(a<=r['time']<b for r in commands for a,b in intervals))
            progress=[]
            for a,b in intervals:
                for identity,journal in journals.items():
                    during=[r for r in journal if a<=r['time']<=b and r.get('position')]
                    if len(during)>1 and math.dist(during[0]['position'],during[-1]['position'])>.5:
                        progress.append(dict(id=identity,start=a,end=b))
            check('onboard_physical_progress_offline',bool(progress),progress)
        compute=Compute(binary,ROOT/'models/mission-lidar.json');replayed=[];mismatches=[]
        try:
            for row in rows:
                actual=compute.call(op='locate',ranges=row['observation']['ranges'],height=1.1,prior=row['prior']);replayed.append(actual)
                if actual!=row['result']:mismatches.append(row['observation']['sequence'])
        finally:compute.close()
        check('independent_raw_replay',not mismatches,mismatches[:20])
        arrival_support={}
        for person in roster:
            last=next(((r,v) for r,v in reversed(list(zip(rows,replayed))) if r['observation']['id']==person and r['observation']['time']<=objective_end+1e-8),None)
            if last is None:arrival_support[person]={'valid':False};continue
            row,value=last;age=objective_end-row['observation']['time'];position=value.get('position')
            arrival_support[person]=dict(age_seconds=age,position=position,valid=position is not None and age<=.4+1e-8 and math.dist(position,scene['destination']['position'])<.9)
        check('arrival_supported_by_fresh_fixes',all(v['valid'] for v in arrival_support.values()),arrival_support)
        if evacuation:
            plans=[r['value'] for r in session if r['kind']=='evacuation_plan']
            check('one_recorded_evacuation_plan',len(plans)==1)
            if plans and exits:
                safe=plans[0]['route'][-1];support={}
                for person in roster:
                    samples=[(r,v) for r,v in zip(rows,replayed) if r['observation']['id']==person and end-2.4<=r['observation']['time']<=end+1e-8]
                    stamps=[r['observation']['time'] for r,v in samples]
                    valid=True
                    for n in range(11):
                        t=end-2+n*.2;i=bisect.bisect_right(stamps,t+1e-8)-1
                        if i<0 or t-stamps[i]>.4+1e-8 or not samples[i][1].get('position') or math.dist(samples[i][1]['position'],safe)>=.9:valid=False
                    support[person]=dict(valid=valid,samples=len(samples))
                check('outdoor_exit_supported_for_full_roster_2s',all(v['valid'] for v in support.values()),support)
                check('reference_roster_reaches_outdoor_area',all(any(r['observation']['id']==p and
                      end-.4<=r['observation']['time']<=end+1e-8 and math.dist(r['reference'][:2],safe)<.9 for r in rows) for p in roster))
            handovers=[r['value'] for r in session if r['kind']=='coverage_handover']
            if closures:
                check('reroute_has_physical_coverage_handover',len(handovers)==1 and bool(withdrawals),handovers)
            for handover in handovers:
                identity=handover['id'];t=handover['time']
                perched=[r for r in journals[identity] if r['time']>=t and r.get('anchor') and
                         r.get('target',{}).get('id')==handover['site']['id']]
                # Onboard journals sample at a different cadence to ground
                # ranging. Require physical perching before departure here;
                # the raw-ranging check below verifies the full lead time.
                check('handover_'+identity+'_landed_before_departure',bool(perched and withdrawals) and perched[0]['time']<withdrawals[0])
                used=[r['observation']['time'] for r,v in zip(rows,replayed) if r['observation']['time']>=t and identity in v.get('used',[])]
                check('handover_'+identity+'_new_measurements_before_departure',bool(used and withdrawals) and min(used)<withdrawals[0]-2)
                if handover['op']=='relocate':
                    accepted=[(r,v) for r,v in zip(rows,replayed) if t-.4<=r['observation']['time']<=t+1e-8]
                    check('handover_'+identity+'_remaining_nodes_support_everyone',all(any(r['observation']['id']==p and
                          v.get('position') and len(set(v['used'])-{identity})>=3 for r,v in accepted) for p in roster))
        all_errors=[math.dist(v['position'],r['reference'][:2]) for r,v in zip(rows,replayed) if v.get('position') is not None]
        independently=dict(samples=len(rows),fixes=len(all_errors),valid_ratio=len(all_errors)/len(rows),p95=p95(all_errors),maximum=max(all_errors,default=None))
        check('summary_consistent_with_raw',all((abs(summary['positioning'][k]-v)<1e-9 if isinstance(v,(int,float)) else summary['positioning'][k]==v) for k,v in independently.items()),independently)
        per_person={};all_grids={}
        for person in roster:
            selected=[(r,v) for r,v in zip(rows,replayed) if r['observation']['id']==person and start-1e-8<=r['observation']['time']<=end+1e-8]
            stamps=[r['observation']['time'] for r,v in selected]
            def metrics(items):
                errors=[math.dist(v['position'],r['reference'][:2]) for r,v in items if v.get('position') is not None]
                return dict(samples=len(items),valid=len(errors),raw_ratio=len(errors)/len(items) if items else None,p95=p95(errors),max_error=max(errors,default=None))
            stats=metrics(selected);grid=[]
            for n in range(math.floor((end-start)/.2+1e-8)+1):
                t=start+n*.2;i=bisect.bisect_right(stamps,t+1e-8)-1
                valid=i>=0 and t-stamps[i]<=.4+1e-8 and selected[i][1].get('position') is not None
                grid.append((t,valid))
            stats.update(grid_total=len(grid),grid_valid=sum(v for t,v in grid),grid_ratio=sum(v for t,v in grid)/len(grid),max_measurement_gap=max((b-a for a,b in zip([start]+stamps,stamps+[end])),default=0))
            occluded=[(r,v) for r,v in selected if any(crosses(r['reference'],[a['x'],a['y']],wall) for a in r['observation']['ranges'] for wall in scene['walls'])]
            stats['occluded']=metrics(occluded)
            occluded_stamps={r['observation']['time'] for r,v in occluded}
            occluded_grid=[valid for t,valid in grid if (lambda i: i>=0 and stamps[i] in occluded_stamps)(bisect.bisect_right(stamps,t+1e-8)-1)]
            stats['occluded'].update(grid_total=len(occluded_grid),grid_ratio=sum(occluded_grid)/len(occluded_grid) if occluded_grid else None,grid_definition='grid cells whose latest packet has at least one independently ray-tested wall obstruction')
            if failures:
                stats['node_failure_segment']=metrics([(r,v) for r,v in selected if r['observation']['time']>=failures[0]['time']])
                fault_grid=[valid for t,valid in grid if t>=failures[0]['time']]
                stats['node_failure_segment'].update(grid_total=len(fault_grid),grid_ratio=sum(fault_grid)/len(fault_grid) if fault_grid else None)
            check('person_'+person+'_accuracy_and_availability',stats['p95'] is not None and stats['p95']<=.75 and stats['raw_ratio']>=.95 and stats['grid_ratio']>=.95,stats)
            per_person[person]=stats;all_grids[person]=grid
        detail['window']={'start':start,'end':end,'sim_seconds':end-start}
        if failures:
            ft=failures[0]['time'];failed=next(s['failed'] for s in states if s['failed'])
            check('failed_node_unused_after_2s',all(failed not in v.get('used',[]) for r,v in zip(rows,replayed) if r['observation']['time']>=ft+2))
            common=[(t,all(all_grids[p][i][1] for p in roster)) for i,(t,_) in enumerate(all_grids[roster[0]]) if t>=ft]
            since=None;recovery=None
            for t,valid in common:
                if not valid:since=None
                elif since is None:since=t
                elif t-since>=5-1e-8:recovery=since-ft;break
            check('recovery_with_5s_continuity',recovery is not None and recovery<=30,{'recovery_delay':recovery})
            dispatched_spare=[e for e in events if e['code']=='replacement_dispatched']
            completed_spare=[e for e in events if e['code']=='replacement_complete']
            check('automatic_replacement_completed',len(dispatched_spare)==1 and len(completed_spare)==1,
                  {'dispatch':dispatched_spare,'complete':completed_spare})
        if scenario=='unknown':
            injections=json.loads((directory/'injections.json').read_text())
            unknown=[e for e in injections if e['kind']=='unknown_node_stop' and e.get('coordinator_not_notified')]
            check('unknown_identity_fault_injected',len(unknown)==1,unknown)
            check('unknown_detected_within_2s',bool(unknown and failures) and 0<=failures[0]['time']-unknown[0]['time']<=2)
        dispatched={x['value']['id'] for x in session if x['kind']=='onboard_command' and x['value']['command']['op']=='deploy'}
        check('nonempty_unique_deployments',len(dispatched)>=5 and len(dispatched)==sum(x['kind']=='onboard_command' and x['value']['command']['op']=='deploy' for x in session))
        check('real_takeoff_landing_each_dispatched',all('Takeoff detected' in (directory/(d+'.log')).read_text() and 'Disarmed by landing' in (directory/(d+'.log')).read_text() for d in dispatched))
        bad_anchor=[]
        for d,journal in journals.items():
            for row in journal:
                if row.get('anchor') and (row['armed'] or row['state']!='anchor' or not .3<row['position'][2]<.7):bad_anchor.append((d,row['time']))
        check('anchors_only_after_disarm_perch',not bad_anchor,bad_anchor[:10])
        collisions=[];max_speed=0.;prev={};obstacles=scene['walls']+[x['box'] for x in scene['obstacles']]
        for row in truth:
            for d,p in row['drones'].items():
                active_obstacles=obstacles+([evacuation['closure']['box']] if closures and row['time']>=closures[0] else [])
                if p[2]>.9 and any(x-.24<p[0]<x+w+.24 and y-.24<p[1]<y+h+.24 for x,y,w,h in active_obstacles):collisions.append({'id':d,'time':row['time'],'position':p})
                if d in prev:
                    t,q=prev[d];dt=row['time']-t
                    if dt>.02:max_speed=max(max_speed,math.dist(p,q)/dt)
                prev[d]=(row['time'],p)
        check('physical_clearance',not collisions,collisions[:20]);check('no_teleport',max_speed<6,max_speed)
        check('landing_at_docks',all(d not in dispatched or math.dist(prev[d][1][:2],drone['dock'])<.8 and prev[d][1][2]<.35 for drone in scene['drones'] for d in [drone['id']]),{d:v[1] for d,v in prev.items()})
        detail['business_events']=[e for e in events if e['code'] in ('deploy','task','evacuation_requested','recall')]
        expected=['deploy','task','evacuation_requested','recall'] if evacuation else ['deploy','task','recall']
        check('at_most_4_business_operations' if evacuation else 'at_most_3_business_operations',[e['code'] for e in detail['business_events']]==expected)
        return dict(schema='mosaic.ma1.independent-run.v2',scope='single run; does not certify all A01-A13',scenario=scenario,run=str(directory),passed=all(v=='PASS' for v in checks.values()),checks=checks,details=detail)
    except Exception as e:
        return dict(run=str(directory),passed=False,checks=checks,error=type(e).__name__+': '+str(e),details=detail)
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--binary',type=Path,required=True)
    parser.add_argument('--scenario',choices=('baseline','default','unknown','sensors','obstacle','offline'),required=True,
                        help='Declared before execution; never infer missing faults as a baseline')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=check_run(args.run,args.binary,args.scenario)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='details'}))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
