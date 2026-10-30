# Private Station recording handoff

The native Records API now accepts a reviewed selection of a Station recording
at `POST /desktop/v1/requests/{request_id}/station-recordings`. Body:
`{"recording_id":"<UUID>","expected_sha256":"<64 lowercase hex characters>"}`.

Set `TOWNLIGHT_STATION_URL` to the trusted Station origin. Connections use HTTPS
or explicit loopback HTTP, without redirects or environment proxy discovery.
The caller must possess a current authorized Records session in
`X-Townlight-Session`. Clerk capture permission does not grant Records attachment
permission. No proof is persisted with a recording or transferred to media workers.

Records downloads from the configured Station API, checks recording identity,
completed/private state, SHA-256 and byte count, and stages files in its own
managed store. It calls the existing canonical attachment workflow and preserves
Station source/meeting/agenda/actor provenance in document metadata and the audit
log. The source request is row-locked; deterministic request/recording/hash identity
and the canonical attachment check make lost-response retries idempotent.
Corrupt existing evidence is never overwritten. Incomplete transfers are rejected.

`GET /desktop/v1/station/context?capability=capture|read` validates the existing
native session, enabled modules and mapped SQL actor for Station. Capture requires
Meetings permission; read requires Meetings or Records permission. It is enabled
only when a trusted Station origin is explicitly configured.

Attaching a recording creates **private evidence under review**. It does not
create a release copy, approve disclosure, publish playback or grant public access.
Records continues to own disclosure decisions. Missing/failed Station transfers
leave existing evidence intact and return an error. The paired acceptance uses
actual HTTP apps and private PostgreSQL, not mocked providers.

The 0.2.0 live increment also preserves `capture_kind`, configured `live_source`, stop attribution and attempt history. A live recording has no retained original-file hash; its verified captured output is the evidence, with live input configuration and timing/stop provenance. The operator catalog uses canonical Records `request_id` UUIDs; legacy presentation `id` values must not be used as API identifiers.
