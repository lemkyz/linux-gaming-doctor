# P11 — Game Knowledge Engine

P11 turns the canonical corpus into game-aware diagnostic candidates without pretending that a known
issue is automatically the cause of a user's symptom.

Knowledge packs match games by Steam AppID first and normalized exact name only as a fallback. A pack
contains references to canonical corpus cases; classification and evidence status are read from the corpus
at runtime so the knowledge layer cannot silently drift away from evidence authority.

## Candidate, not diagnosis

A pack match means “these corpus cases may be relevant to this game.” It does **not** mean the condition is
present. Even an exact, confirmed corpus case still requires its real preconditions to be observed by later
session, differential, or policy probes.

`REPORTED` and `UNCONFIRMED` evidence is always returned as `candidate_only` and can never authorize an
automatic repair.

## Initial packs

P11 seeds RE Engine / REFramework family mappings, GTA V / GTA V Enhanced policy mappings, and a baseline
Dead by Daylight identity pack. The pack format is deliberately declarative so future contributions can add
game knowledge without adding hard-coded diagnosis branches.

## Privacy

The local coverage scan uses Steam AppIDs internally but does not emit installed game names or paths.
