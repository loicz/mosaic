# Development

Run the [quick start](../README.md) to build `mosaic_mission`, `mosaic-mission-compute`, and the C++ unit-test executable. Python checks use the standard library. Node.js enables the console unit checks. The [CI workflow](../.github/workflows/ci.yml) runs CMake and CTest without PX4 or Gazebo.

Use `-DMOSAIC_ENABLE_SANITIZERS=ON` in a separate build directory for AddressSanitizer and UndefinedBehaviorSanitizer. Use `-DBUILD_TESTING=OFF` for a C++-only build.

| Path | Responsibility |
| --- | --- |
| `include/mosaic/mission.hpp`, `src/mission.cpp` | A*, robust UWB estimation, and lidar risk inference |
| `apps/mission_compute.cpp` | Command-line entry point for the C++ engine |
| `scripts/mission_agent.py` | Per-aircraft sensor processing, local map, planning, and MAVLink |
| `scripts/mission_runtime.py` | Coordination, state freshness, faults, and recordings |
| `scripts/mission_radio.py` | Ranging simulation and independent error reference |
| `scripts/mission_world.py`, `scripts/mission_sitl.py` | Gazebo world generation and PX4 lifecycle |
| `dashboard/mission/` | Local JavaScript and Three.js console |
| `config/mission-rescue.json` | Reference map, roster, routes, and candidate anchor sites |
| `tests/` | Core, integration, browser, and independent acceptance checks |

## Model training

The simulator loads the checked-in weights. To reproduce training with NumPy in the prepared toolchain, run:

```sh
python3 -B scripts/mission_env.py -- python3 -B scripts/mission_train.py --help
```

Choose a fresh output path. The model JSON records the seeds, sample counts, and held-out confusion matrix.

## Browser checks

Set up the [runtime](mission-operations.md), then launch the automatic mission in a separate terminal. Install Playwright and Chromium into the ignored runtime directory:

```sh
npm install --prefix .runtime/browser playwright@1.62.0
.runtime/browser/node_modules/.bin/playwright install chromium
export MOSAIC_PLAYWRIGHT_PACKAGE="$(pwd)/.runtime/browser/node_modules/playwright"
node tests/browser_mission.cjs http://127.0.0.1:8766 .runtime/browser-results --wait-tracking
```

Use the distro's browser libraries if Playwright reports missing system dependencies. The live test covers WebGL, 2D, replay, browser freshness, command checks, keyboard controls, responsive layouts, and offline assets.

To test the interface with a completed authentic recording, start a local static server and point the recording test at the session:

```sh
python3 -m http.server 8767 --bind 127.0.0.1 --directory dashboard/mission
# In another terminal, with MOSAIC_PLAYWRIGHT_PACKAGE configured:
node tests/browser_mission_recording.cjs http://127.0.0.1:8767 \
  /path/to/completed-fault-run/session.jsonl /tmp/mosaic-recorded-ui
```

The recorded-browser test intercepts API calls and checks presentation and request routing. Use the live check to exercise the actual server. See the [verification guide](mission-delivery.md) for flight acceptance and lifecycle checks.
