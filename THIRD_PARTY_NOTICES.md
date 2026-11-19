# Third-party components and data

| Component | Location / source | License / scope |
|---|---|---|
| nlohmann/json | `third_party/nlohmann/json.hpp` | MIT; original notice retained in the header and `third_party/JSON-LICENSE.MIT` |
| Three.js 0.180.0 | `dashboard/mission/vendor/three/` | MIT; license and npm integrity/hash manifest bundled for offline rendering |
| PX4 v1.17.0 | Official PX4-Autopilot, commit `d6f12ad1c4f70ad3230afd7d86e971421e02fef4` | BSD-3-Clause; runtime bundle retains upstream LICENSE; reusable development toolchain also retains source |
| PX4 Gazebo models | Official PX4-gazebo-models, commit `b6127f4ec20de867e215fb5f78ae88b80f371909` | Upstream license retained; collision-based visual proxies preserve physical parameters |
| Gazebo Harmonic 8.15.0 / Ubuntu 24.04 | Isolated toolchain and offline runtime bundle | Distribution copyright/license files retained under `/usr/share/doc`; not MOSAIC-authored code |
| Python, NumPy, pymavlink and build tools | Isolated toolchain and runtime bundle | Respective upstream distribution terms and installed license metadata apply |
| JetBrains Mono Nerd Font, regular | `dashboard/mission/fonts/JetBrainsMonoNerdFont-Regular.ttf`; Nerd Fonts v3.4.0 / JetBrains Mono 2.304, upstream source and SHA-256 in `JetBrainsMono-manifest.json` | SIL OFL 1.1; original `JetBrainsMono-OFL.txt` bundled; used by the English UI and map labels |
| Local lidar MLP | `models/mission-lidar.json` | Project-generated synthetic training data and weights; reproducible script, no third-party model weights |
| Playwright / Chromium | Optional browser verification environment | Not needed for normal demo; not included in the offline runtime bundle |

Mission observations, radio noise and model training samples are synthetic.
Browser screenshots depict the project's own UI and simulated observations.
No external personal images, camera footage or recorded audio are used by the
current mission system.

Validation scope and results are described in [the verification guide](docs/mission-delivery.md).
