#!/usr/bin/env python3
"""Paired raw-ranging ablation, not another flight or a video-system benchmark.

Only valid when a spare extends the fixed network without moving old anchors.
Both solvers get identical original measurements, timestamps and missing data;
the fixed-network branch omits only the newly deployed evacuation anchor.
"""
import argparse
import bisect
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from mission_compute import Compute


def compare(directory, binary):
    records=[json.loads(x) for x in (directory/'session.jsonl').read_text().splitlines()]
    scene=next(r['value']['scene'] for r in records if r['kind']=='manifest')
    events=[r['value'] for r in records if r['kind']=='event']
    handovers=[r['value'] for r in records if r['kind']=='coverage_handover']
    assert len(handovers)==1 and handovers[0]['op']=='deploy', 'comparison requires a spare and unchanged original anchors'
    assert not any(r['kind']=='onboard_command' and r['value']['command']['op']=='relocate' for r in records)
    extra=handovers[0]['id']
    start=next(e['time'] for e in events if e['code']=='evacuation_started')
    end=next(e['time'] for e in events if e['code']=='personnel_evacuated')
    rows=[json.loads(x) for x in (directory/'ranges.jsonl').read_text().splitlines()]
    results={};compute=Compute(binary,ROOT/'models/mission-lidar.json')
    try:
        for name in ('fixed','extended'):
            prior={};samples={p['id']:[] for p in scene['roster']}
            for row in rows:
                observation=row['observation'];identity=observation['id'];stamp=observation['time']
                ranges=[r for r in observation['ranges'] if name=='extended' or r['id']!=extra]
                value=compute.call(op='locate',ranges=ranges,height=1.1,prior=prior.get(identity))
                position=value.get('position')
                if position:prior[identity]=position
                if start<=stamp<=end:
                    samples[identity].append((stamp,math.dist(position,row['reference'][:2]) if position else None))
            people={}
            for identity,points in samples.items():
                stamps=[t for t,_ in points];errors=sorted(e for _,e in points if e is not None)
                grid=[];gap=longest=0.
                for n in range(math.floor((end-start)/.2)+1):
                    stamp=start+n*.2;i=bisect.bisect_right(stamps,stamp+1e-8)-1
                    valid=i>=0 and stamp-stamps[i]<=.4+1e-8 and points[i][1] is not None
                    grid.append(valid);gap=0. if valid else gap+.2;longest=max(longest,gap)
                people[identity]=dict(samples=len(points),valid=len(errors),raw_ratio=len(errors)/len(points),
                    grid_ratio=sum(grid)/len(grid),longest_gap_seconds=longest,
                    p95=errors[math.ceil(len(errors)*.95)-1] if errors else None)
            results[name]=people
    finally:compute.close()
    passed=all(results['extended'][p]['grid_ratio']>=.95 and
               results['extended'][p]['grid_ratio']>results['fixed'][p]['grid_ratio'] and
               results['extended'][p]['longest_gap_seconds']<results['fixed'][p]['longest_gap_seconds']
               for p in results['extended'])
    return dict(passed=passed,scope='paired raw-ranging ablation in one simulated evacuation; no physical or video comparison',
                extra_anchor=extra,start=start,end=end,results=results)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--binary',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    report=compare(args.run,args.binary)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report));raise SystemExit(0 if report['passed'] else 1)
