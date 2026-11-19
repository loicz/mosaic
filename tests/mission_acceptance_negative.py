#!/usr/bin/env python3
"""Corrupt copies of an accepted fault run; never change original evidence."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
from mission_acceptance import check_run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--binary',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    original=check_run(args.run,args.binary,'default')
    results={'original_passed':original['passed'],'cases':{}}
    with tempfile.TemporaryDirectory(prefix='mosaic-negative-') as temporary:
        cases=[('missing-fault-events','required_faults_present'),
                              ('empty-physics','required_nonempty_logs'),
                              ('tampered-summary','summary_consistent_with_raw'),
                              ('cross-wall-route','personnel_route_clearance'),
                              ('cross-wall-reference','personnel_motion_clearance')]
        if 'evacuation_before_recovery' in original['checks']:
            cases.extend([('missing-personnel-exit','evacuation_before_recovery'),
                          ('premature-recall','no_aircraft_recalled_before_roster_exit')])
        for case,expected in cases:
            directory=Path(temporary)/case;directory.mkdir()
            for source in args.run.iterdir():
                if source.is_file() and source.suffix in ('.jsonl','.json','.log'):
                    shutil.copyfile(source,directory/source.name)
            if case=='missing-fault-events':
                file=directory/'session.jsonl'
                rows=[json.loads(line) for line in file.read_text().splitlines()]
                rows=[r for r in rows if not (r['kind']=='event' and r['value']['code'] in
                      ('anchor_failed','link_lost','link_restored'))]
                file.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            elif case=='empty-physics':
                (directory/'physics-truth.jsonl').write_text('')
            elif case=='tampered-summary':
                file=directory/'metrics.json';value=json.loads(file.read_text())
                value['positioning']['p95']=.000001;file.write_text(json.dumps(value))
            elif case=='cross-wall-route':
                file=directory/'session.jsonl'
                rows=[json.loads(line) for line in file.read_text().splitlines()]
                next(r['value']['scene'] for r in rows if r['kind']=='manifest')['personnel_route'][2]=[13.5,10.4]
                file.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            elif case=='cross-wall-reference':
                file=directory/'ranges.jsonl'
                rows=[json.loads(line) for line in file.read_text().splitlines()]
                rows[len(rows)//2]['reference']=[13.03,8.1,1.1]
                file.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            elif case in ('missing-personnel-exit','premature-recall'):
                file=directory/'session.jsonl'
                rows=[json.loads(line) for line in file.read_text().splitlines()]
                if case=='missing-personnel-exit':
                    rows=[r for r in rows if not (r['kind']=='event' and r['value']['code']=='personnel_evacuated')]
                else:
                    next(r['value'] for r in rows if r['kind']=='onboard_command' and r['value']['command']['op']=='recall')['time']=0.
                file.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            report=check_run(directory,args.binary,'default')
            results['cases'][case]={'rejected':not report['passed'],
                                   'expected_check':expected,'checks':report['checks']}
    results['passed']=results['original_passed'] and all(v['rejected'] and
                      v['checks'].get(v['expected_check'])=='FAIL' for v in results['cases'].values())
    args.output.write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results));return 0 if results['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
