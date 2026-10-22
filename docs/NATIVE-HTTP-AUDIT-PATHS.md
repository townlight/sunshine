# Native HTTP audit paths

Native Records routes containing request and document UUIDs can exceed the audit
action column's 100-character limit. The HTTP middleware now uses the bounded
`METHOD http_request` action for those routes. Normal shorter actions keep their
existing representation. The complete method, path, query, status and actor remain
in the existing audit entry; complete request details participate in its hash.
Paths longer than the resource ID's 255-character limit use a `sha256:` lookup key,
with the complete path retained in hashed details. No historical entry or hash is
rewritten, and no schema or shared Core contract changes.

The focused regression uses the real native Records release-copy route, a normal
route and an over-255 path. Denied unauthenticated writes remain denied; each leaves
an HTTP audit entry and a valid audit chain. Canonical domain action/artifact
logging and human review/release controls are unchanged.

This repair is included in the separate unsigned Townlight Planning P6 candidate.
It does not alter the sources or assets of the historical signed 1.4 installer.
