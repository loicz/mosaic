#!/usr/bin/env python3
"""Fail closed when any declared MA-1 run or A01-A13 subreport is missing.

The plan fixes run IDs/scenarios and per-gate report paths before execution.
This aggregates independent reports; it never substitutes for their checks.
"""
import argparse
import hashlib
import json
from pathlib import Path


def evaluate(plan, directory):
    failures=[];reports={}
    expected={f'A{i:02}' for i in range(1,14)}
    if set(plan.get('gates',{}))!=expected: failures.append('Plan must cover exactly A01-A13')
    runs=plan.get('runs',[])
    required={'baseline','default-4103','default-4104','default-4105','unknown',
              'obstacle-a','obstacle-b','lidar','position','ranges','offline'}
    if not required<={r['coverage'] for r in runs}: failures.append('Required matrix coverage is missing')
    paths={r['report'] for r in runs}
    paths.update(path for values in plan.get('gates',{}).values() for path in values)
    for name in sorted(paths):
        try:
            path=directory/name;data=json.loads(path.read_text())
            reports[name]={'passed':data.get('passed') is True,
                           'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            if not reports[name]['passed']: failures.append(f'Failed subreport: {name}')
        except (OSError,ValueError) as error:
            reports[name]={'passed':False,'error':str(error)}
            failures.append(f'Missing or invalid subreport: {name}')
    gates={gate:('PASS' if paths and all(reports[p]['passed'] for p in paths) else 'FAIL')
           for gate,paths in plan.get('gates',{}).items()}
    return dict(schema='mosaic.ma1.matrix.v1',passed=not failures and all(v=='PASS' for v in gates.values()),
                gates=gates,failures=failures,reports=reports)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=evaluate(json.loads(args.plan.read_text()),args.plan.parent)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result));return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
