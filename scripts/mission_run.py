#!/usr/bin/env python3
"""Start the offline command console and real multi-PX4/Gazebo mission."""
from __future__ import annotations
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import multiprocessing as mp
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit, parse_qs

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--scene',type=Path,default=ROOT/'config/mission-rescue.json')
    parser.add_argument('--run-dir',type=Path)
    parser.add_argument('--auto',action='store_true',help='Run deployment, personnel task, evacuation and fleet recovery')
    parser.add_argument('--faults',action='store_true',help='Exercise link loss and anchor failure during automatic demo')
    parser.add_argument('--reroute',action='store_true',help='Close the east passage before automatic evacuation; verify coverage for the west detour')
    parser.add_argument('--exit-on-complete',action='store_true')
    parser.add_argument('--timeout',type=float,default=0)
    parser.add_argument('--inside',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--managed',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if not args.inside:
        from mission_env import command,DEFAULT_TOOLCHAIN,managed_call
        # The host entry point keeps all simulation dependencies inside the
        # reusable toolchain. User paths are translated only within allowed roots.
        scene=args.scene.resolve()
        try: relative=scene.relative_to(ROOT)
        except ValueError: parser.error('--scene must be within this project')
        forwarded=['python3','-B','/mosaic/scripts/mission_run.py','--inside','--managed','--port',str(args.port),
                   '--scene',str(Path('/mosaic')/relative)]
        if args.run_dir:
            directory=args.run_dir.resolve()
            try: relative=directory.relative_to(DEFAULT_TOOLCHAIN/'work')
            except ValueError: parser.error(f'--run-dir must be within {DEFAULT_TOOLCHAIN / "work"}')
            forwarded+=['--run-dir',str(Path('/work')/relative)]
        for name in ('auto','faults','reroute','exit_on_complete'):
            if getattr(args,name): forwarded.append('--'+name.replace('_','-'))
        if args.timeout: forwarded+=['--timeout',str(args.timeout)]
        return managed_call(command(DEFAULT_TOOLCHAIN,forwarded))
    from mission_runtime import Mission
    from mission_replay import Replay
    build=Path('/work/mosaic-build')
    subprocess.run(['cmake','-S',str(ROOT),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release'],check=True,stdout=subprocess.DEVNULL)
    subprocess.run(['cmake','--build',str(build),'--target','mosaic-mission-compute','-j4'],check=True,stdout=subprocess.DEVNULL)
    scene=json.loads(args.scene.read_text())
    directory=args.run_dir or Path(tempfile.mkdtemp(prefix='mission-',dir='/work'))
    directory.mkdir(parents=True,exist_ok=True)
    if (directory/'session.jsonl').exists(): parser.error('run directory already contains a session; choose a new directory')
    mission=Mission(scene,directory,Path('/work/PX4-Autopilot'),build/'mosaic-mission-compute',ROOT)
    (directory/'controller.pid').write_text(str(os.getpid()))
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM): signal.signal(sig,lambda *_:stop.set())
    if args.managed:
        def control_input():
            for line in sys.stdin:
                if line.strip()=='__mosaic_shutdown__':stop.set();return
            stop.set()  # Loss of the owner is also a shutdown request.
        threading.Thread(target=control_input,daemon=True).start()
    assets=ROOT/'dashboard/mission'
    replay=Replay(directory/'session.jsonl')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_): pass
        def reply(self,status,data,content_type='application/json; charset=utf-8'):
            self.send_response(status); self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; font-src 'self'")
            self.end_headers()
            try: self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError): pass
        def do_GET(self):
            path=urlsplit(self.path).path
            if path=='/api/state':
                state=mission.state or dict(phase='starting',time=0,token=mission.token)
                self.reply(200,json.dumps(state,ensure_ascii=False,allow_nan=False).encode()); return
            if path=='/api/replay':
                query=parse_qs(urlsplit(self.path).query)
                try:
                    value=replay.frame(int(query['frame'][0])) if 'frame' in query else replay.index()
                except (ValueError,IndexError):
                    self.reply(400,b'{"error":"frame"}'); return
                self.reply(200,json.dumps(value,ensure_ascii=False).encode()); return
            relative='index.html' if path=='/' else path.lstrip('/')
            file=(assets/relative).resolve()
            if not file.is_relative_to(assets.resolve()) or not file.is_file(): self.reply(404,b'{}'); return
            self.reply(200,file.read_bytes(),mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
        def do_POST(self):
            origin=self.headers.get('Origin')
            if origin and origin!=f'http://127.0.0.1:{args.port}' and origin!=f'http://localhost:{args.port}':
                self.reply(403,b'{"error":"origin"}'); return
            if self.path!='/api/command' or self.headers.get('X-Mosaic-Token')!=mission.token:
                self.reply(403,b'{"error":"token"}'); return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=4096: raise ValueError()
                action=json.loads(self.rfile.read(length))
                if not isinstance(action,dict) or action.get('op') not in {'deploy','task','evacuate','block_route','recall','disconnect','reconnect','interference','fail_anchor'}: raise ValueError()
            except (ValueError,TypeError): self.reply(400,b'{"error":"command"}'); return
            mission.actions.put(action); self.reply(202,b'{"accepted":true}')

    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    print(f'MOSAIC http://127.0.0.1:{args.port}  |  session {directory}',flush=True)
    started=time.monotonic(); last_phase=None; actions=set()
    try:
        mission.start()
        while not stop.is_set():
            mission.tick()
            if mission.phase!=last_phase:
                print(f'{mission.radio.time:.1f}s {mission.phase}',flush=True); last_phase=mission.phase
            if args.auto:
                if args.reroute and mission.phase=='objective_complete' and not mission.route_blocked:
                    if not any(d['state'] in ('takeoff','transit','landing','calibrating') for d in mission.telemetry.values()):
                        mission.actions.put(dict(op='block_route'))
                for phase,op in [('idle','deploy'),('ready','task'),('objective_complete','evacuate'),('evacuated','recall')]:
                    if op=='evacuate' and args.reroute and not mission.route_blocked: continue
                    if mission.phase==phase and op not in actions:
                        mission.actions.put(dict(op=op)); actions.add(op)
                if args.faults:
                    if mission.phase=='deploying' and 'disconnect' not in actions and any(d['state']=='transit' for d in mission.telemetry.values()):
                        mission.actions.put(dict(op='disconnect')); actions.add('disconnect')
                    if mission.phase=='tracking' and mission.radio.time-mission.radio.start>8 and 'fail_anchor' not in actions:
                        mission.actions.put(dict(op='fail_anchor')); actions.add('fail_anchor')
            if args.exit_on_complete and mission.phase=='complete': break
            if args.timeout and time.monotonic()-started>args.timeout: raise TimeoutError('mission run timeout')
            time.sleep(.04)
        return 0
    finally:
        server.shutdown(); server.server_close(); mission.close()
        print(f'Session saved: {directory}',flush=True)


if __name__=='__main__':
    mp.set_start_method('spawn')
    raise SystemExit(main())
