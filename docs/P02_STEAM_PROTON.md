# P02 — Steam + Proton Discovery / Health Engine

P02 maps the compatibility stack without changing it.

It discovers:

- native and Flatpak Steam roots without emitting their absolute paths;
- Steam library topology and filesystem class;
- installed app manifests and whether their install directory still exists;
- per-app and global Steam compatibility-tool selections;
- official Proton and custom compatibility tools;
- Proton `compatdata` presence and minimum Wine-prefix integrity;
- duplicate or malformed manifests;
- selected Proton tools that cannot be found locally;
- stale compatdata and Windows-shared filesystem risk boundaries.

The engine does **not** delete prefixes, switch Proton versions, move libraries, install packages,
or edit Steam configuration. Those actions belong to later transactional-repair phases.

## CLI

```bash
./bin/gaming-doctor steam
./bin/gaming-doctor steam --json
```

## Important semantics

`prefix.status=absent` or `not_initialized` is not automatically a fault. A game may be native,
may never have been launched through Proton, or Steam may still be using automatic compatibility.
Only structurally incomplete existing prefixes are reported as findings.
