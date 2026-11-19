# Operations

## Runtime setup

The live demo needs a Linux x86-64 host with Python 3.11 or newer, bubblewrap, and unprivileged user namespaces. For example, install the host dependencies with `sudo apt-get install python3 bubblewrap` on Ubuntu 24.04. Use a modern WebGL browser. Allow about 8 GB for the runtime and at least 8 GB of available memory.

Obtain the prepared runtime from the project maintainer. The toolchain includes an Ubuntu 24.04 userspace, Gazebo Harmonic 8.15.0, PX4 1.17.0, and Python dependencies. If you receive a `MOSAIC-0.5.0-offline.tar.gz` archive with its matching checksum, verify and extract it in the download directory:

```sh
sha256sum --check MOSAIC-0.5.0-offline.tar.gz.sha256
tar -xzf MOSAIC-0.5.0-offline.tar.gz
```

Run this checkout from its root against the prepared toolchain:

```sh
export MOSAIC_TOOLCHAIN=/absolute/path/to/MOSAIC-0.5.0/toolchain
python3 -B scripts/mission_run.py --auto --faults --reroute
```

The default location is `.runtime/toolchain/`. `MOSAIC_TOOLCHAIN` takes precedence. The launcher expects these paths within the toolchain:

| Path | Purpose |
| --- | --- |
| `ubuntu24/` | Ubuntu userspace, compilers, Gazebo libraries, and tools |
| `work/PX4-Autopilot/` | PX4 SITL build and Gazebo vehicle models |
| `work/venv/` | Python simulation dependencies |
| `work/` | Generated worlds, builds, logs, and recordings |

The archive's own `run.py` uses the source code bundled inside that archive. For this checkout, use `scripts/mission_run.py`. Inside bubblewrap, the source tree is mounted at `/mosaic` and toolchain work files at `/work`.

## Launch options

Open <http://127.0.0.1:8766> after starting. Run without arguments for manual operation. The server listens on loopback. Press **Ctrl+C** in the launching terminal and wait for `Session saved`.

| Option | Behavior |
| --- | --- |
| `--auto` | Deploy, start the personnel task, evacuate, and recover the fleet. |
| `--faults` | Add a 25-second command outage and one ranging-node failure during the automatic mission. |
| `--reroute` | With `--auto`, close the east passage and exercise the west detour. |
| `--exit-on-complete` | Save the final state and exit. Omit this to leave the browser available for replay. |
| `--timeout 720` | Return failure when the wall-clock run limit expires. |
| `--port 8770` | Serve the console on a different loopback port. |
| `--scene PATH` | Use a custom scenario under the source checkout. |
| `--run-dir PATH` | Use a new host path inside the toolchain's `work/` directory. |

For a reference run with network isolation:

```sh
python3 -B scripts/mission_env.py --isolated-network -- \
  python3 -B /mosaic/scripts/mission_run.py --inside \
  --auto --faults --exit-on-complete --timeout 720 --run-dir /work/offline-check
```

The isolated network namespace prevents the host browser from connecting. Use the normal launcher for the interactive demo.

## Recordings

| File | Contents |
| --- | --- |
| `session.jsonl` | Scenario, commands, events, and console snapshots |
| `D*-onboard.jsonl` | Per-aircraft sensing, inference, and task state |
| `ranges.jsonl` | Raw ranges, position estimates, and independent evaluation reference |
| `physics-truth.jsonl` | Simulation truth for independent checks |
| `D*.log`, `D*/log/*.ulg`, `gazebo.log` | Flight-controller and simulator logs |
| `metrics.json` | Recorded summaries of errors, availability, recovery, and final phase |

The default output is a new `work/mission-*` directory. The console can replay recorded snapshots with mission controls locked. Use an independent acceptance check to recompute rates from the original records.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Missing isolated toolchain | Verify that `MOSAIC_TOOLCHAIN` points to the prepared `toolchain/` directory. |
| Namespace creation fails | Run on a Linux system that permits bubblewrap user namespaces. |
| Port already in use | Use `--port 8770` or stop your previous session. |
| Another session holds the SITL lock | Wait for that toolchain's current session to stop. |
| 3D view fails to initialize | Try a WebGL-capable browser and check the browser console. The 2D view is also available. |
