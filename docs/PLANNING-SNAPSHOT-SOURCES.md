# Planning snapshot sources for Records — development integration

The paired Planning P3/P4 candidate exports reviewed immutable source snapshots.
The runtime explicitly composes its public snapshot provider with the existing
Meetings and Zoning public providers and Access advice. Existing installer
profiles do not enable Planning; native Planning controls and identity remain P5.
This source adapter does not change the signed Townlight 1.4 installer.

Records staff use the existing authenticated native capability boundary:

- `POST /desktop/v1/planning-sources/search` accepts a query and returns permitted
  public source metadata and an excerpt.
- `POST /desktop/v1/requests/{id}/planning-sources` accepts source_id and
  expected_sha256. The provider is resolved again; changed hashes return 409 and
  unavailable/restricted sources are not attached.

Attachment stores exact snapshot bytes in the managed Records file store, with
source/version/hash/citation provenance and the existing canonical attachment
and audit records. Retries reuse identical evidence. It does not approve or
publish a response. The existing human review, release-copy, exemption decision,
response approval, export completion and fulfillment workflow remains required.

Records rechecks Planning source permissions and hashes when retrieving linked
documents/request content, preparing/completing exports and fulfilling a request.
The Planning provider in turn rechecks pinned policy and linked Meetings/Zoning
evidence. Provider absence, revocation or changed bytes blocks use; retained
historical files are never substituted as permission to release. Existing audit
and file evidence is preserved. Restoring permission can resolve the same
immutable snapshot again without changing its bytes.

The application binds the trusted provider to request database sessions. Domain
callers outside HTTP must bind `session.info['planning_source_provider']` explicitly;
missing composition fails closed for Planning attachments. Other document origins
retain their existing behavior. No request accepts provider URLs or code.

`tests/test_desktop_zoning.py` continues its real persisted Code/Zoning/Meetings
fixture through `planning_connected_acceptance.check_planning`. The continuation
imports a fictional adopted plan, edits/reviews analysis, selects actual persisted
linked evidence, exports an immutable public snapshot, attaches exact bytes in
Records, and completes the existing human-controlled release. It also checks
closed-session revocation before export/fulfillment, restoration, later amendments
and staff edits, private-note exclusion, staff-only snapshot exclusion and Access
advice. This is API/PostgreSQL acceptance, not an installed desktop claim.

The paired CI pins Planning and the composition runtime to exact source commits.
Those pins are test inputs; they do not update the historical installer payload.
Historical releases/tags/assets remain unchanged. No signing or release publication
is part of this increment.
