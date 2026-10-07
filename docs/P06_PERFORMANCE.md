# P06 — Performance Diagnostic Engine

P06 adds a privacy-preserving, read-only snapshot of performance-related evidence.

It intentionally does **not** infer “CPU bottleneck”, “thermal throttling”, or “GPU bottleneck” from one number. A single sample is context. Later session-timeline and differential phases will correlate these signals with actual frametime events.

## Collected evidence

- CPU frequency driver, governors, EPP, current/min/max frequencies and boost availability;
- 1/5/15 minute load averages;
- memory availability and swap use;
- Linux PSI pressure for CPU, memory and I/O;
- thermal-zone temperatures where the kernel exposes them;
- laptop power profile, AC state and battery status;
- NVIDIA utilization, temperature, P-state, clocks, power and VRAM telemetry through read-only `nvidia-smi`;
- GameMode and MangoHud availability.

## Evidence discipline

P06 does not flag `powersave`, high GPU utilization, or an installed overlay as a fault by itself. Snapshot findings are deliberately conservative and require later correlation before the project attributes a game symptom to them.

No P06 operation changes governors, clocks, power profiles, GameMode, MangoHud, swap or thermal policy.
