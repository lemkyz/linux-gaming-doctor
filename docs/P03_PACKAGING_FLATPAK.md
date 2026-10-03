# P03 — Packaging + Flatpak Boundary Engine

P03 answers a question that ordinary game diagnostics often miss: **which packaging boundary is the game actually crossing?**

The same Steam library can behave differently under a native RPM/DEB package and the Steam Flatpak because the sandbox has its own runtime, driver extensions, filesystem declarations, device visibility and environment.

P03 is read-only. It records evidence for later differential tests and repairs; it does not call `flatpak override`, install runtimes, change permissions or modify Steam.

## Evidence collected

- native Steam presence and package ownership;
- host package system;
- user/system Steam Flatpak installations;
- selected Flatpak runtime and branch;
- privacy-preserving sandbox capability categories (Wayland/X11/audio/network/devices/udev/home/host);
- external Flatpak Steam library visibility without emitting their paths;
- host NVIDIA module version and matching Flatpak GL/GL32 extension presence;
- packaging conflicts such as simultaneous native + Flatpak Steam.

## Findings

P03 may emit:

- `MULTIPLE_STEAM_PACKAGING_MODELS`
- `NATIVE_STEAM_PACKAGE_OWNER_UNKNOWN`
- `FLATPAK_STEAM_LIBRARY_PERMISSION_GAP`
- `FLATPAK_NVIDIA_RUNTIME_MISMATCH`

A finding is evidence, not permission to mutate the system. Repair execution remains reserved for the later transactional repair phases.
