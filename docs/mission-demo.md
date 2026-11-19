# Demo walkthrough

Run the [quick start](../README.md) or set up the [simulation runtime](mission-operations.md). For a hands-off demo use:

```sh
python3 -B scripts/mission_run.py --auto --faults --reroute
```

Open <http://127.0.0.1:8766>. For a guided demonstration start the launcher without flags and operate the console:

1. Wait for **Awaiting deployment**, then select **Deploy fleet**. Watch the drones take off and land at selected anchor sites. An anchor appears as active after it has settled and calibrated.
2. When the network is ready, select **Start personnel task**. Select a roster entry to inspect its estimate and trail. Use **2D** or **3D** to see the route and anchors.
3. Expand **Fault injection**. Disconnect and reconnect the command link, disable a ranging anchor, or toggle ranging interference. Compare the stale console observations with onboard execution and the subsequent service recovery.
4. At the indoor objective, choose **Close east passage** for the alternate route, or leave the passage open to use the south exit. Select **Start evacuation** and observe the coverage check and any repositioning.
5. When every enrolled person is accounted for outdoors, select **Recover fleet**. Wait for the deployed drones to land and the active-anchor count to reach zero.
6. Open replay to inspect earlier states. Press **Ctrl+C** in the launching terminal to end the session after review.

The map distinguishes **Current position**, **Last-known position**, and **Uncertain position**. A trail gap indicates a missing fix or a connection that crosses a known wall. The local recordings support independent verification of mission state and positioning.
