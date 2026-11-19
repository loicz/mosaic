#!/usr/bin/env python3
"""Run the simulation toolchain in a task-owned, rootless Linux filesystem.

No Windows mounts, host devices, user homes, or host package databases are bound.
The Ubuntu filesystem and downloads live in the selected toolchain directory.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOOLCHAIN = Path(os.environ.get('MOSAIC_TOOLCHAIN', ROOT / '.runtime/toolchain')).expanduser().resolve()


def managed_call(arguments: list[str]) -> int:
    """Keep terminal signals out of bwrap until the controller cleans up.

    Killing bwrap first would invoke --die-with-parent before PX4 process groups
    can be reaped. A private stdin message asks the controller to stop normally.
    """
    process=subprocess.Popen(arguments,stdin=subprocess.PIPE,start_new_session=True)
    requested=False
    def stop(*_):
        nonlocal requested
        if requested or process.poll() is not None:return
        requested=True
        try:
            process.stdin.write(b'__mosaic_shutdown__\n');process.stdin.flush()
        except (BrokenPipeError,OSError):pass
    previous={sig:signal.signal(sig,stop) for sig in (signal.SIGINT,signal.SIGTERM)}
    try:return process.wait()
    finally:
        process.stdin.close()
        for sig,handler in previous.items():signal.signal(sig,handler)


def command(toolchain: Path, arguments: list[str], network: bool = True) -> list[str]:
    rootfs = toolchain / 'ubuntu24'
    if not (rootfs / 'bin/sh').exists():
        raise SystemExit(f'Missing isolated toolchain: {rootfs}\n'
                         'For the full demo, extract the offline runtime release and run its run.py.\n'
                         'For this source checkout, set MOSAIC_TOOLCHAIN to that release\'s toolchain directory.\n'
                         'See docs/mission-operations.md; cloning source does not install PX4/Gazebo.')
    bubblewrap = shutil.which('bwrap')
    if not bubblewrap:
        raise SystemExit('bubblewrap is required for the isolated development environment')
    result = [bubblewrap, '--die-with-parent', '--unshare-user', '--uid', '0', '--gid', '0',
              '--bind', str(rootfs), '/', '--proc', '/proc', '--dev', '/dev',
              '--bind', str(toolchain / 'work'), '/work',
              '--bind', str(ROOT), '/mosaic', '--chdir', '/mosaic', '--clearenv',
              '--setenv', 'PATH', '/work/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
              '--setenv', 'PYTHONDONTWRITEBYTECODE', '1',
              '--setenv', 'DEBIAN_FRONTEND', 'noninteractive',
              '--setenv', 'XDG_CACHE_HOME', '/work/cache',
              '--setenv', 'XDG_RUNTIME_DIR', '/work/runtime',
              '--setenv', 'CCACHE_DIR', '/work/ccache',
              '--setenv', 'QT_QPA_PLATFORM', 'offscreen',
              '--setenv', 'LIBGL_ALWAYS_SOFTWARE', '1']
    if network:
        result += ['--ro-bind', '/etc/resolv.conf', '/etc/resolv.conf']
    else:
        result += ['--unshare-net']
    return result + arguments


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolchain', type=Path, default=DEFAULT_TOOLCHAIN)
    parser.add_argument('--isolated-network', action='store_true')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    arguments = args.command
    if arguments and arguments[0] == '--':
        arguments = arguments[1:]
    if not arguments:
        parser.error('provide a command after --')
    toolchain = args.toolchain.resolve()
    for directory in ('work', 'work/cache', 'work/runtime', 'work/ccache'):
        (toolchain / directory).mkdir(parents=True, exist_ok=True)
    os.chmod(toolchain / 'work/runtime', 0o700)
    if any(Path(arg).name=='mission_run.py' for arg in arguments) and '--inside' in arguments:
        if '--managed' not in arguments:arguments+=['--managed']
        return managed_call(command(toolchain,arguments,not args.isolated_network))
    return subprocess.call(command(toolchain, arguments, not args.isolated_network))


if __name__ == '__main__':
    raise SystemExit(main())
