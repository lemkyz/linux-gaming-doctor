# Linux Gaming Doctor

**Don't tweak. Diagnose.**

Linux Gaming Doctor is an evidence-driven troubleshooting and repair layer for Linux gaming.
It is designed to answer a harder question than “which launch option should I paste?”:

> **What actually broke, at which boundary, and what is the smallest safe action that fixes it?**

The project starts from a canonical corpus of real-world Linux gaming failure modes and builds a diagnostic graph around them.

## Principles

- **Observe before changing anything.**
- **No placebo tweaks.** A repair is recommended only when its precondition is observed.
- **Boundary-aware diagnosis.** Host → sandbox → launcher → runtime → prefix → game → compositor → audio/input/output.
- **Differential testing.** Compare working vs failing states instead of guessing.
- **Every mutation is reversible.** Plan → snapshot → apply → verify → keep/rollback.
- **“Upstream / unsupported” is a valid successful diagnosis.**
- **Privacy by default.** Reports must scrub usernames, home paths, serials, MAC/IP addresses and tokens.

## Roadmap

P00 Corpus + schemas  
P01 System Facts  
P02 Steam/Proton  
P03 Packaging/Flatpak  
P04 GPU/Vulkan  
P05 Display/Wayland  
P06 Performance  
P07 Audio  
P08 Input  
P09 Storage  
P10 Launcher/Heroic/Lutris  
P11 Game Knowledge  
P12 Session Timeline  
P13 Last-Known-Good  
P14 Differential A/B  
P15 Interference Engine  
P16 Repair Planner  
P17 Transaction/Rollback  
P18 Upstream Classifier  
P19 Privacy Report  
P20 GUI/CLI  
P21 Fedora acceptance  
P22 Linux distro expansion

## P00

P00 freezes the diagnostic vocabulary and corpus shape before implementation. Every later detector must be able to point to evidence using this schema.

Validate the repository with:

```bash
python3 tools/validate_corpus.py
python3 -m unittest discover -s tests -v
```

## P01 — System Facts Engine

The first executable collector is deliberately read-only:

```bash
./bin/gaming-doctor facts
./bin/gaming-doctor facts --json
```

It inventories host/session/CPU/GPU/Vulkan/Steam/filesystem/audio/input/security/power state without collecting hostname, username, hardware serials, network identifiers or the user's home path.

P01 is a **facts layer**, not a diagnosis layer. Later phases consume these observations before deciding whether a fault condition actually exists.

## P02 — Steam + Proton health map

P02 adds a read-only compatibility-stack view:

```bash
./bin/gaming-doctor steam
./bin/gaming-doctor steam --json
```

It discovers Steam installations/libraries, installed app manifests, Proton/custom compatibility tools,
compatibility-tool selection, compatdata/prefix integrity and filesystem risk boundaries. It never
silently deletes a prefix or switches Proton versions. P02 only creates evidence for later differential
tests and transactional repairs.

## P03 — Packaging + Flatpak boundary map

P03 adds a read-only packaging/sandbox view:

```bash
./bin/gaming-doctor packaging
./bin/gaming-doctor packaging --json
```

It distinguishes native Steam from the Steam Flatpak, inventories sandbox capabilities without leaking
filesystem paths or environment values, checks configured external-library visibility, and correlates
an NVIDIA host driver with the Flatpak GL/GL32 runtime extensions that must match it. P03 never changes
Flatpak overrides, installs runtimes or rewrites Steam configuration.
