# P04 — GPU + Vulkan Diagnostic Engine

P04 turns “my NVIDIA driver is installed” into a boundary-aware GPU health report.

A Linux gaming machine can have a loaded kernel driver while the Vulkan userspace stack, 32-bit runtime,
render-node permissions or hybrid-GPU enumeration is still wrong. P04 checks those layers separately.

P04 is strictly read-only.

## Collected evidence

- PCI display GPUs and bound kernel drivers from sysfs;
- DRM render nodes and current-user access;
- Vulkan physical-device enumeration from `vulkaninfo --summary` when available;
- Vulkan ICD inventory without emitting absolute filesystem paths;
- Fedora/RPM 32-bit Vulkan readiness for the detected vendor set;
- NVIDIA kernel module vs `nvidia-smi` userspace driver version;
- `switcherooctl` hybrid-GPU availability.

## Important interpretation rule

`nvidia-smi` passing is **not** equivalent to Vulkan passing.
Likewise, a Vulkan probe passing does not prove that every 32-bit Proton title has the required i686 runtime.
P04 records each boundary independently so later phases can run game-specific differential tests.

## Findings

P04 can emit evidence-backed findings such as:

- `GPU_DRIVER_UNBOUND`
- `DRM_RENDER_NODE_ACCESS_DENIED`
- `VULKAN_PROBE_FAILED`
- `GPU_NOT_ENUMERATED_BY_VULKAN`
- `NVIDIA_SMI_FAILED`
- `NVIDIA_KERNEL_USERSPACE_VERSION_MISMATCH`
- `VULKAN_32BIT_PACKAGE_MISSING`

No finding in P04 applies a repair. Mutations remain reserved for the transactional repair phases.
