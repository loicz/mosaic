# Verification

MOSAIC separates software checks, simulated flight and browser evidence, and physical evaluation. Use the [project requirements](project-goals.md) and [acceptance plan](mission-independent-acceptance.md) to scope a report.

## Checks

| Layer | Entry point | What it exercises |
| --- | --- | --- |
| Core | `ctest --test-dir build --output-on-failure` | C++ planning and ranging, storage, fault behavior, roster and evacuation rules, repository integrity, and console unit checks when Node.js is available |
| Simulated flight | `scripts/mission_run.py` | PX4 and Gazebo sensor/physics loop, autonomous deployment, localization, faults, evacuation and recovery |
| Independent flight analysis | `tests/mission_acceptance.py` | Recomputed fixes, physical trajectories, elapsed recovery, failure evidence, and final state |
| Browser | `tests/browser_mission.cjs` | Actual console, freshness, replay, responsive layout, and local assets |
| Shutdown | `tests/mission_shutdown.py` | SIGINT through the public launcher and cleanup of its descendant processes |
| Runtime packaging | `scripts/mission_package.py` | Bundle creation, file hashes, and a launcher for the prepared toolchain |

For a current-source run, set `MOSAIC_TOOLCHAIN`, then choose a fresh work directory and run the fault and detour scenario:

```sh
python3 -B scripts/mission_run.py --auto --faults --reroute \
  --exit-on-complete --timeout 720 --run-dir "$MOSAIC_TOOLCHAIN/work/verify-detour"
python3 -B scripts/mission_env.py -- python3 -B tests/mission_acceptance.py \
  --scenario default --run /work/verify-detour \
  --binary /work/mosaic-build/mosaic-mission-compute \
  --output /work/verify-detour/acceptance.json
```

Run the terminal lifecycle check with a separate work directory:

```sh
python3 -B tests/mission_shutdown.py \
  --output /tmp/mosaic-shutdown-results \
  --run-dir "$MOSAIC_TOOLCHAIN/work/verify-shutdown"
```

Archive the original records separately with hashes for the checked source, scenario, model, toolchain and outputs. Document the exact seed, flags, failures and scope of each run. See [operations](mission-operations.md) for recording fields and [development](development.md) for browser setup.
