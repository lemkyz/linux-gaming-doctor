# Terminology

- **fact** — observed system state; never inferred from a user complaint alone.
- **probe** — read-only operation that produces facts/evidence.
- **boundary** — interface between subsystems, e.g. kernel → sandbox, Steam Input → game.
- **condition** — machine-testable predicate required before a diagnosis or repair applies.
- **diagnosis** — evidence-backed explanation of the narrowest failing boundary.
- **repair** — local state change intended to restore expected behavior.
- **workaround** — local state change that avoids, but does not fix, an upstream defect.
- **verification** — post-action check that proves the target symptom changed as expected.
- **rollback** — restoration of all mutated state when verification fails or the user requests undo.
- **interference** — failure caused only by a specific combination of otherwise-working features.
- **last-known-good** — recorded working fingerprint for a game/session.
