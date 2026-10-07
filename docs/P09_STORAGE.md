# P09 — Storage / Filesystem Diagnostic Engine

P09 maps storage conditions that can break or destabilize Linux gaming without changing mounts, files,
prefixes, permissions, or Steam libraries.

It distinguishes native Linux filesystems from Windows-shared and network filesystems, reduces mount
options to privacy-safe capability booleans, measures free space/inode availability, and inspects each
Steam library plus its compatdata filesystem boundary.

## Evidence discipline

A game living on NTFS/exFAT is not automatically considered broken. The engine records it as a risk
boundary because game-data access and Proton-prefix semantics are different questions. Existing compatdata
on a Windows-shared filesystem is surfaced separately.

P09 also records host install-path lengths, but a long path is classified as `UNKNOWN` until a later
differential test proves the application is path-sensitive.

## Privacy

Reports do not contain absolute paths, mount sources/targets, usernames, filesystem UUIDs, volume labels,
or device serial numbers. Only filesystem type, mount capability flags, capacity statistics and anonymized
library IDs are emitted.

No P09 operation creates a symlink, remounts a filesystem, moves compatdata, deletes caches, or writes a
probe file.
