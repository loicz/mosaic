# Evacuation and anchor coverage

The personnel task has an indoor objective and a separate outdoor assembly gate. The mission coordinator keeps its localization network in service until the entire roster has fresh fixes inside the selected outdoor assembly area for two continuous seconds.

The reference scenario offers the south exit and a west detour. Before evacuation begins, the operator may close the east passage. Gazebo inserts the closure as a physical obstacle. Aircraft save the declared region as a no-fly constraint for replanning, including during recall. Personnel wait at the objective while the coordinator validates the alternate route.

## Coverage handover

1. Evaluate route coverage from estimated anchor positions, the modeled radio range, and available personnel fixes.
2. If a candidate could improve coverage, dispatch the reserve aircraft where possible. If the reserve is already in use, move a healthy anchor only when the remaining measured network can keep tracking the full roster at the hold point.
3. Wait for landing and calibration. Verify new ranges and fresh personnel fixes before releasing the route.
4. If coverage remains insufficient, hold personnel at the objective and keep fleet recall locked.

The reference route switch occurs before personnel withdraw. The scenario assumes a fixed cooperative roster, validated routes, simulated local odometry, and a modeled radio environment. Use the [demo walkthrough](mission-demo.md) to exercise both routes and the [verification guide](mission-delivery.md) to evaluate a run.
