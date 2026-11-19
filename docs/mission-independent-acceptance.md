# Independent acceptance plan

Declare the source snapshot, simulator versions, seeds, fault schedule and statistical windows before testing. Record each criterion as PASS, FAIL, or BLOCKED and link to the supporting output. Follow the [project requirements](project-goals.md) for the reference scenario and its assumptions.

| ID | Acceptance criterion |
| --- | --- |
| A01 | Build in a fresh directory and run CTest. Independently unpack the offline bundle and match its hashes and prerequisites to the source. |
| A02 | Start with zero active anchors. Verify actual takeoff, flight, landing, calibration, tracking, outdoor assembly and return. All dispatched aircraft land and disarm, leaving zero active anchors. |
| A03 | Confirm each onboard process uses local sensor inputs, performs inference and planning, and changes plans or actions when confronted with a hidden obstacle. Show that inference affects a decision. |
| A04 | Interrupt the two-way command link for 25 simulated seconds during flight. Confirm dropped commands and telemetry, continued progress on accepted tasks, and synchronization without duplicate assignment. |
| A05 | Disable one ranging anchor without informing the coordinator of its identity. Exclude the failed anchor within two simulated seconds and restore service within 30 simulated seconds. Track five seconds of continuous valid fixes and verify reserve deployment separately. |
| A06 | Recompute 2D P95 error of at most 0.75 m and at least 95% valid updates for every roster member, keeping missing updates in the denominator. Report occlusion and fault intervals separately. |
| A07 | Expire observations after 1.5 simulated seconds of stale data during a command outage. For HTTP loss or a frozen stream, show stale or paused state within three wall-clock seconds. Recover on new observations. |
| A08 | Interrupt lidar, local pose and personnel ranges separately for five simulated seconds each. Check safe holding or uncertainty, automatic resumption, and protection against arrival from old data. |
| A09 | Trace the truth boundary. Changing only the evaluation reference while holding observations fixed leaves estimates and mission decisions unchanged. |
| A10 | Complete the nominal mission in four operator actions at most. Verify 2D, 3D, roster selection, freshness, control lock during replay and narrow viewports in a real browser. |
| A11 | Run the default fault scenario with seeds 4103, 4104 and 4105. Test two separate hidden-obstacle placements with passable routes. Require the nominal and default runs to complete within 720 wall-clock seconds each. |
| A12 | Compare algorithms on identical ranging inputs for at least three predeclared seeds. Report error and availability, including failures. |
| A13 | Complete a fault run in an isolated network namespace, confirm local-only browser assets, and test Ctrl+C during idle and flight. Require termination within 20 wall-clock seconds with no remaining descendants. |

For evacuation, count localization from personnel entry through outdoor assembly confirmation. Compute both the raw solve rate and the share of valid fixes on a 0.2-second simulation-time grid with a 0.4-second freshness window. Report console outages separately from ranging availability. Include a default-route run, a detour with reserve deployment, and a detour with an already-used reserve that requires a healthy node to move. Verify actual measured coverage handover, continuous authorized movement, and recall only after the assembly gate. When coverage is insufficient, verify that the system continues to hold.

Keep severe out-of-scope interruptions such as loss of every range in a separate degradation report. The relevant acceptance behavior is safe holding and recovery after fresh observations return.

Use `tests/mission_acceptance_negative.py` on scratch copies of a fault run to verify that missing events, empty logs and tampered summaries are rejected. Use `tests/mission_matrix.py` to verify the coverage and integrity of the A01–A13 report set. See [verification](mission-delivery.md) for entry points.
