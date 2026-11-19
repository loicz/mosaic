# Project goals

MOSAIC demonstrates autonomous deployment of a temporary localization network at an emergency training site. Drones explore a known single-floor layout, perch to become UWB anchors, track a fixed roster of cooperative personnel, recover service after faults, and withdraw after everyone reaches outdoor assembly.

The reference scenario uses one indoor objective, two verified evacuation routes, five initial anchor sites and a reserve drone. Seven candidate sites are available, with S7 reserved for evacuation coverage. Aircraft transit the entrance sequentially. A failed ranging node is assumed capable of returning. Local odometry, battery input, perching, radio propagation, and personnel movement are simulated.

| ID | Requirement | Acceptance evidence |
| --- | --- | --- |
| M01 | Offline demo | One public launcher starts the prepared runtime and cleanly stops its child processes. |
| M02 | Deployment without preinstalled active anchors | Site allocation, flight, sensing, perching, calibration, and network readiness execute in simulation. |
| M03 | Independent onboard sensing and avoidance | Each aircraft runs local inference and planning. A hidden obstacle measurably changes an action or plan. |
| M04 | Personnel localization | Per-person P95 error is at most 0.75 m and valid updates are at least 95%. Keep missed fixes in the denominator. |
| M05 | Command-link outage | Onboard tasks continue for at least 20 simulated seconds and the console expires old observations and recovers on new ones. |
| M06 | Ranging failure | A faulty anchor is excluded and positioning service recovers within 30 simulated seconds. |
| M07 | Evacuation and fleet recovery | Fresh fixes place the full roster in outdoor assembly before recall. All dispatched aircraft then return and land, with zero remaining active anchors. |
| M08 | Console | Test 2D, 3D, roster selection, state freshness, controls, and narrow viewports in a real browser. |
| M09 | Traceable recording | Version scenario, seed, commands, faults, and states. Label replay as historical. |
| M10 | Ground-truth boundary | Only sensor generation and evaluation use hidden truth. Personnel positions are derived from ranging observations. |
| M11 | Consistency | Independently build current source and match the documentation, model, configuration, and release manifest. |
| M12 | Portable runtime | Independently unpack and verify the prepared environment, sources, notices, and launch instructions. |
| M13 | Real flight control in simulation | Multiple PX4 instances control Gazebo physics and receive simulated sensors. |
| M14 | Evacuation handover | A declared closure triggers a verified detour. Existing anchors maintain fixes during handover. New anchors count after landing, calibration, and fresh ranging. Personnel hold when coverage is insufficient. |

Keep synthetic inputs, software-in-the-loop results, and physical evidence distinct. Report failure cases and distinguish current, last-known, and uncertain fixes. Physical deployment requires independent validation of the simulated interfaces.

See the [acceptance plan](mission-independent-acceptance.md) and [verification guide](mission-delivery.md).
