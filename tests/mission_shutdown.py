#!/usr/bin/env python3
"""Exercise terminal Ctrl+C on the public launcher, including all descendants."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request


def children(pid):
    result=[]
    try:direct=(Path('/proc')/str(pid)/'task'/str(pid)/'children').read_text().split()
    except FileNotFoundError:return result
    for value in direct:
        child=int(value);result.append(child);result.extend(children(child))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--launcher',type=Path,default=Path(__file__).resolve().parents[1]/'scripts/mission_run.py')
    parser.add_argument('--run-dir',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    with (args.output/'launcher.log').open('w') as log:
        child=subprocess.Popen([sys.executable,'-B',str(args.launcher),'--port','8770','--run-dir',str(args.run_dir)],
                               stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        descendants=[]
        try:
            deadline=time.monotonic()+65
            while time.monotonic()<deadline:
                if child.poll() is not None:raise RuntimeError('launcher exited before ready')
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8770/api/state',timeout=1) as response:state=json.load(response)
                    if state['phase']=='idle':break
                except (OSError,ValueError):pass
                time.sleep(.3)
            else:raise TimeoutError('mission did not become ready')
            descendants=children(child.pid)
            assert len(descendants)>=14,'did not observe actual multi-process simulation'
            os.killpg(child.pid,signal.SIGINT)  # Same foreground process-group signal as Ctrl+C.
            code=child.wait(timeout=20)
            remaining=[]
            for pid in descendants:
                try:
                    command=(Path('/proc')/str(pid)/'cmdline').read_bytes()
                    if command:remaining.append(pid)
                except FileNotFoundError:pass
            result=dict(passed=code==0 and not remaining,exit_code=code,
                        descendants_checked=len(descendants),remaining=remaining,signal='SIGINT to outer foreground process group')
            (args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
            assert result['passed'],'public launcher did not cleanly stop all owned processes'
        finally:
            if child.poll() is None:child.terminate();child.wait(timeout=20)


if __name__=='__main__':main()
