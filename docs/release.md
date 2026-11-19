# Runtime packaging

The source checkout contains the mission code, scenario, local model, browser assets, and tests. The offline runtime requires a prepared Linux toolchain. See [operations](mission-operations.md) for the expected layout.

Build a bundle in a fresh output path:

```sh
export MOSAIC_TOOLCHAIN=/absolute/path/to/toolchain
python3 -B scripts/mission_package.py --output dist/MOSAIC-0.5.0-offline.tar.gz
```

The archive contains the project, Ubuntu userspace, Gazebo, PX4 runtime assets, Python dependencies, a top-level `run.py`, and the project file hashes in `BUNDLE.json`. The adjacent `.sha256` file covers the archive.

Independently unpack it into an empty directory. Verify the archive checksum and project hashes, rebuild and run CTest from the extracted source, and run the bundled launcher from idle through recovery. Test shutdown and check for remaining processes. Record which scenario and runtime were tested and retain the verification record with the bundle.

Keep runtime archives and raw logs outside the tracked source tree. Preserve bundled upstream notices and follow [LICENSE.md](../LICENSE.md) and [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) when distributing any artifacts.
