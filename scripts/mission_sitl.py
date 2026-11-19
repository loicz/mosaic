"""Lifecycle for real Gazebo and PX4 processes in the Linux toolchain."""
from __future__ import annotations
import os
import fcntl
import json
from pathlib import Path
import signal
import subprocess
import time
from mission_world import generate


class Sitl:
    def __init__(self, scene, run_directory: Path, px4: Path, partition: str, count=None):
        self.directory = run_directory
        self.px4 = px4
        self.scene = scene
        self.count = count or len(scene['drones'])
        self.children = []
        self.logs = []
        self.lock = None
        self.environment = dict(os.environ, GZ_PARTITION=partition, GZ_IP='127.0.0.1',
            GZ_SIM_RESOURCE_PATH=str(run_directory/'models')+':'+str(px4/'Tools/simulation/gz/models'),
            LIBGL_ALWAYS_SOFTWARE='1', QT_QPA_PLATFORM='offscreen')

    def spawn(self, arguments, name, cwd=None, extra=None):
        log = (self.directory / (name+'.log')).open('w')
        self.logs.append(log)
        process = subprocess.Popen(arguments, cwd=cwd, env=dict(self.environment, **(extra or {})),
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.children.append(process)
        with (self.directory/'processes.jsonl').open('a') as journal:
            journal.write(json.dumps(dict(pid=process.pid,name=name,command=arguments))+'\n')
        return process

    def start_world(self):
        self.lock = (self.directory.parent/'mission-sitl.lock').open('a')
        try: fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close(); self.lock=None
            raise RuntimeError('Another MOSAIC SITL session is running in this toolchain')
        path = generate(self.scene, self.directory, self.px4/'Tools/simulation/gz/models', self.count)
        process = self.spawn(['gz', 'sim', '-r', '-s', '--headless-rendering', str(path)], 'gazebo')
        deadline = time.monotonic()+40
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('Gazebo exited; see gazebo.log')
            check = subprocess.run(['gz', 'service', '-i', '-s', '/world/mosaic/scene/info'],
                env=self.environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=5)
            if 'Service providers' in check.stdout: return
            time.sleep(.4)
        raise RuntimeError('Gazebo scene service did not become ready')

    def start_flight_controllers(self):
        binary = self.px4/'build/px4_sitl_default/bin/px4'
        resources = self.px4/'build/px4_sitl_default/etc'
        # Keep simulated power measurements on the Gazebo clock. A stalled
        # sensor remains subject to PX4's battery-health/arming checks.
        self.spawn(['python3', '-B', str(Path(__file__).with_name('mission_power.py')),
                    '--count', str(self.count), '--journal', str(self.directory/'power.jsonl')], 'power')
        for index, drone in enumerate(self.scene['drones'][:self.count]):
            directory = self.directory/drone['id']
            directory.mkdir(exist_ok=True)
            settings = dict(PX4_SYS_AUTOSTART='4001', PX4_GZ_STANDALONE='1',
                PX4_GZ_WORLD='mosaic', PX4_GZ_MODEL_NAME=drone['id'])
            # Indoor navigation uses the simulated local odometry sensor. No
            # GNSS input or magnetometer heading is required inside the building.
            parameters = dict(EKF2_GPS_CTRL=0, EKF2_EV_CTRL=15, EKF2_HGT_REF=3,
                EKF2_EV_NOISE_MD=1, EKF2_EVP_NOISE=.05, EKF2_EVV_NOISE=.1,
                EKF2_MAG_TYPE=5, COM_ARM_WO_GPS=1, COM_RC_IN_MODE=4,
                COM_RCL_EXCEPT=4, COM_ARM_MAG_STR=0, COM_DISARM_LAND=1,
                COM_OF_LOSS_T=3, MPC_XY_VEL_MAX=2, MPC_XY_CRUISE=1.5,
                MPC_TKO_SPEED=1.2, MPC_LAND_SPEED=.7, COM_DL_LOSS_T=60,
                NAV_DLL_ACT=0, SIM_BAT_ENABLE=0)  # Onboard offboard-link loss remains separately enforced.
            settings.update({'PX4_PARAM_'+key: str(value) for key,value in parameters.items()})
            # x500 sets a new default for NAV_DLL_ACT after environment overrides;
            # an override equal to the original factory default would be lost.
            # Apply the project policy after the upstream startup script finishes.
            startup = directory/'startup.sh'
            startup.write_text('#!/bin/sh\n. '+str(resources/'init.d-posix/rcS')+'\nparam set NAV_DLL_ACT 0\n')
            self.spawn([str(binary), '-i', str(index), '-d', '-s', str(startup), str(resources)], drone['id'], directory, settings)

    def block_passage(self, obstacle):
        """Insert a real collision/lidar obstacle; success must be acknowledged."""
        import xml.etree.ElementTree as ET
        from mission_world import box
        from gz.transport13 import Node
        from gz.msgs10.entity_factory_pb2 import EntityFactory
        from gz.msgs10.boolean_pb2 import Boolean
        root = ET.Element('sdf', version='1.9')
        box(root, obstacle['id'], obstacle['box'], obstacle['height'], '0.85 0.45 0.14 1')
        request = EntityFactory(sdf=ET.tostring(root, encoding='unicode'))
        success, response = Node().request('/world/mosaic/create', request, EntityFactory, Boolean, 3000)
        return success and response.data

    def close(self):
        for child in reversed(self.children):
            if child.poll() is None:
                try: os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError: pass
        for child in self.children:
            try: child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try: os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                child.wait()
        for log in self.logs: log.close()
        if self.lock: self.lock.close(); self.lock=None
