# P07 — Audio Diagnostic Engine

P07 maps the Linux gaming audio path without changing PipeWire, WirePlumber, Bluetooth, or game settings.

It collects service/runtime health, sink/source counts and transport classes, default endpoint resolution,
Bluetooth profile context, PipeWire clock/quantum settings, and aggregate recent xrun evidence.

The privacy boundary is deliberate: reports do not emit endpoint names, Bluetooth addresses, human-readable
device descriptions, raw journal lines, process command lines, or absolute paths.

A Bluetooth headset/hands-free profile is context rather than an automatic fault. It may be the correct
choice when microphone input is needed while also explaining reduced playback quality. Likewise, recent
xruns are evidence to correlate with a game session later; they do not identify the root cause by themselves.

No P07 operation changes profiles, defaults, sample rates, quantum, services, or Bluetooth configuration.
