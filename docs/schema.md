# Storage

No database/schema migrations. Private run directories are scoped by Hermes-home hash and deterministic target/question digest. Each includes provenance.json, evidence.json, report.json and optionally three role request/report JSON pairs. Artifacts are 0600 in 0700 directories. Runtime/private content must never be committed.
