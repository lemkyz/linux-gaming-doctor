# P08 — Input / Controller Diagnostic Engine

P08 maps the host input path without changing controller, Steam Input, udev, Bluetooth, or desktop settings.

It combines `/proc/bus/input/devices`, `/dev/input`, udev properties, hidraw accessibility, `/dev/uinput`,
Steam-named udev-rule presence, the udev database boundary, and device-scope battery state.

The report deliberately excludes human-readable device names, physical device paths, serial numbers and
hardware addresses. Vendor/product IDs are retained because they are necessary to match known controller
compatibility and udev-rule cases.

A generic unreadable input node is not automatically treated as a fault. P08 emits an access finding only
when the node is classified as a gamepad, avoiding the common false-positive where keyboards or system
input devices are intentionally restricted.

Later phases will correlate this host view with Steam Input, SDL and game-session behavior.
