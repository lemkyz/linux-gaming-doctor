# Definition of Done — P00

P00 passes only when:

- exactly 100 canonical complaint records exist;
- every record has a unique stable ID `LGD-0001` … `LGD-0100`;
- every record declares category, symptom, expected classification, probe requirements, mutation policy, and evidence status;
- unknown/unconfirmed cases are explicitly marked and cannot silently become fixes;
- schema validation runs without third-party Python dependencies;
- tests reject duplicate IDs, invalid classifications, repair-without-verification, and mutation-without-rollback;
- the roadmap and product constitution are committed to the repository.
