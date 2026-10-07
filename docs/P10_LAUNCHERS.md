# P10 — Launcher / Heroic / Lutris Boundary Engine

P10 adds the non-Steam launcher boundary without changing launcher configuration.

The collector recognizes native and Flatpak Heroic/Lutris installations, inventories privacy-safe
Heroic installed-record semantics and Lutris game configuration semantics, checks whether configured
absolute install/prefix/executable targets still exist, detects ELF-vs-PE executable type when a resolved
file exists, and records UMU/Wine helper availability.

## Why this is separate from P02

Steam/Proton state and Heroic/Lutris state have different authorities. A healthy Proton installation does
not prove Heroic selected the runner it actually executed, and a launcher saying an installer completed
does not prove the expected executable exists.

P10 therefore establishes metadata truth before P12 session tracing compares configured runner versus
the process that actually launched.

## Corpus coverage established here

P10 creates the static evidence boundary needed for the Heroic/Lutris cases around stale prefixes,
missing executables, accidental compatibility-layer use for native ELF games, and runaway Heroic log
storage. Runner-execution mismatch remains intentionally unresolved until runtime tracing exists.

## Privacy

No game titles, account identifiers, raw configs, raw logs, tokens, or absolute paths are emitted.
Paths may be inspected locally only to answer booleans such as “configured?” and “exists?”.
