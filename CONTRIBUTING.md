# Contributing

Start with the [README](README.md) and [development guide](docs/development.md). The [project requirements](docs/project-goals.md) describe the reference scenario and its acceptance criteria.

When proposing a change, describe the scenario it affects, how to reproduce the behavior, and the checks you ran. Include a seed and launch options for simulation issues. Keep generated build files, runtime toolchains, and raw recordings outside the tracked source tree.

Use C++20 and keep the configured compiler warnings enabled. Run CTest before submitting a change. For changes to flight behavior, the browser console, or process shutdown, also run the relevant integration checks described in the [verification guide](docs/mission-delivery.md). Follow the permissions in [LICENSE.md](LICENSE.md) when using or distributing project materials.
