# P01 — System Facts Engine

P01 establishes the read-only machine fingerprint consumed by later diagnoses.
It does **not** repair, tune, install, enable, disable, restart, or write system configuration.

## Facts collected

- distro/version/variant, kernel and architecture;
- Wayland/X11 session and desktop environment;
- CPU model, logical CPU count and memory size;
- display/3D PCI devices, vendor family and bound driver;
- loaded NVIDIA module version;
- Vulkan ICD manifest inventory and bounded `vulkaninfo --summary` health probe;
- native and Flatpak Steam installation presence;
- root/home filesystem type and mount options, excluding source/device path;
- PipeWire/WirePlumber versions and user-service state;
- input event counts and device names;
- Secure Boot and SELinux state;
- power profile, AC state and battery state.

## Privacy minimization

P01 intentionally does not emit hostname, username, home path, hardware serials,
MAC/IP addresses, account identifiers or tokens.

## CLI

```bash
./bin/gaming-doctor facts
./bin/gaming-doctor facts --json
```
