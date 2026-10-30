# Private Core beta pairing

This source candidate requires the private civiccore==1.3.0.dev1 wheel. Install only into an isolated candidate environment with the matching local wheel; do not resolve against older public releases. No installed application was upgraded.

Catalog loading/listing now uses civiccore.catalog with a complete immutable-version import ledger. Current role checks remain in Records. Deterministic exemption evaluation now uses civiccore.exemptions; old pattern/helper imports remain compatible. Invalid or overly expensive regex rules produce HTTP422 scan incomplete, and grouped patterns return text rather than tuples. The eight existing detector tests and real PostgreSQL/HTTP scans passed. Core admission fixes do not certify every product manifest.

The current flags still lack immutable rule/citation snapshots. Jurisdiction review, shared LLM suggestions, release authority and UI treatment of incomplete scans remain separate acceptance work. Do not infer legal coverage or approval from detector output.
