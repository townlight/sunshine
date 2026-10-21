<a id="civicrecords-ai--gap-list-accuracy-review"></a>

# Townlight Records — Gap List Accuracy Review

**Date:** 2026-04-13  
**Reviewed against:** `CANONICAL-SPEC-GAP-LIST.md` (generated 2026-04-13), `CivicRecordsSpec-canonical.docx` (v2.0, April 12, 2026), and repo at `github.com/scottconverse/civicrecords-ai` HEAD (156 commits, master branch)  
**Method:** Source-level inspection of cloned repo. App was not run; purely visual/layout questions carry less certainty than structural ones.

---

## 1. Where the Gap List Is Right

The gap list correctly describes the broad shape of the codebase. The following items are confirmed present in the repo and match the gap list's claims:

- **Phase 0 complete.** shadcn/ui installed with 12 component files in `frontend/src/components/ui/`, design tokens mapped to CSS variables in `globals.css`, sidebar layout shell in `app-shell.tsx` and `sidebar-nav.tsx`, stat cards, empty states, status badges with icons, typography scale. No gaps.
- **Phase 2 migration.** `787207afc66a_phase2_extensions...` creates 12 new tables (departments, fee_schedules, fee_line_items, request_timeline, request_messages, response_letters, notification_templates, notification_log, prompt_templates, connector_templates, system_catalog, city_profile) and extends existing tables with the columns the canonical spec requires.
- **Backend modules present.** Departments CRUD (`departments/router.py`), city profile CRUD (`city_profile/router.py`, 85 lines), systems catalog loader + router (`catalog/`), connector framework with base + 3 connectors (file_system, imap_email, manual_drop), analytics API (`analytics/router.py`, 99 lines with operational metrics), notification module (`notifications/` with service, SMTP delivery, router), liaison role in user model enum, prompt templates model.
- **Frontend page files exist for all 11 staff workbench routes** (Dashboard, Search, Requests, RequestDetail, Exemptions, DataSources, Ingestion, Users, Onboarding, CityProfile, Discovery) with routes in `App.tsx`.
- **Phase 3 and Phase 4 not started.** No code exists for the public portal, public API, federation, active discovery engine, NER redaction, or any v1.1/v2.0 items. The gap list is correct.
- **WCAG gaps.** Skip-to-content link: confirmed missing (zero grep matches across the frontend). Keyboard navigation: untested. Screen reader testing: not done. These are accurate.

---

## 2. Where the Gap List Is Out of Date

These items are marked as missing or barely started in the gap list, but the repo now has substantive implementations.

### 2.1 Context Manager (gap list says MISSING — actually PARTIAL)

This is the gap list's biggest error. `backend/app/llm/context_manager.py` (199 lines) exists with:

- `TokenBudget` dataclass matching the canonical spec's exact budget partitions (system_instruction: 500, request_context: 500, retrieved_chunks: 5000, exemption_rules: 500, output_reservation: 1500, safety_margin: 192)
- `ContextBlock` abstraction with role tagging and token estimation
- `estimate_tokens()` function (character-based approximation)
- Prompt injection defense with regex pattern detection and sanitization

**What's still missing vs. the canonical spec:** The context manager does not integrate with the `model_registry` table. The spec requires model-aware budgeting — when an admin switches from Gemma 4 (8K) to Llama 3.3 (128K), budgets should auto-adjust via the `context_window_size` column. No `model_registry` lookup was found in the context manager code. This makes it PARTIAL, not DONE, but it is far from missing.

**Corrected status: PARTIAL** (token budgets and assembly built; model-registry integration missing)

### 2.2 Response Letter Generation (gap list says PARTIAL, model-only — actually substantially built)

The gap list says "no evidence of actual LLM-powered generation endpoint." The repo contradicts this:

- `backend/app/requests/router.py` has a `generate_response_letter` endpoint (line 783+) that assembles request context, calls Ollama with a municipal-records-officer system prompt, and stores the generated content as a `ResponseLetter` record
- Template-based fallback generation exists if LLM is unavailable (`_generate_template_letter`)
- GET endpoint retrieves the latest letter; PATCH endpoint supports status transitions (draft → approved → sent) with role-based approval gating (only reviewers/admins can approve)
- Timeline and audit log entries written on generation

**What's still missing vs. the canonical spec:** The frontend `RequestDetail.tsx` has no "Generate Response Letter" button — the backend capability is not exposed in the UI. The spec also calls for a rich text editor for clerk editing; no rich text editor library appears in the frontend dependencies. And the context assembly in the generation endpoint does not appear to use the `context_manager.py` module's budget system — it does its own inline prompt assembly.

**Corrected status: Backend DONE, Frontend MISSING**

### 2.3 Audit Retention Cleanup (gap list says PARTIAL — actually DONE)

`backend/app/ingestion/scheduler.py` has a `cleanup_audit_logs` Celery task registered as a daily periodic task (86400 seconds) that reads `settings.audit_retention_days`, calculates a cutoff date, and archives then deletes old entries. This matches what the canonical spec requires.

**Corrected status: DONE**

### 2.4 Public RBAC Role (gap list says NOT STARTED — role exists in model)

The `public` role is defined in the user model's role enum. No public-facing routes or middleware enforce it yet, so the role exists as scaffolding, not as a functional capability. But "not started" is inaccurate.

**Corrected status: PARTIAL** (enum exists; no enforcement or public routes)

---

## 3. Where the Gap List Is Too Optimistic

These items are marked as DONE in the gap list but do not meet the canonical spec's definition of complete.

### 3.1 Notification Service (gap list says DONE — actually PARTIAL)

The gap list marks this as done based on the existence of `notifications/` with `service.py`, `smtp_delivery.py`, and `router.py`. The code exists. However:

- **The canonical spec (Section 7.1) requires every status transition to trigger a notification if a template exists for that transition.** The request router's status-transition handlers write to `request_timeline` and `audit_log`, but notification dispatch calls were not found wired into those handlers.
- **The README itself still says SMTP email delivery is "not yet implemented"** — the repo's own documentation contradicts the gap list's "DONE" status.
- **The seed script (`scripts/seed_templates.py`) seeds compliance/disclosure templates, not the 7 notification event templates** the canonical spec defines in Section 8.4 (received, clarification, assigned, deadline approaching, deadline overdue, records ready, request closed). No seed script for notification templates was found.

**Corrected status: PARTIAL** (infrastructure exists; not wired into workflow transitions; notification templates not seeded; README says not implemented)

### 3.2 Fee Tracking (gap list says DONE — actually PARTIAL)

The repo has fee models (`models/fees.py`, 42 lines), fee schedule CRUD in the admin router, and fee line item endpoints on requests (`GET /requests/{id}/fees`, `POST /requests/{id}/fees`). This is real. However, the canonical spec calls for:

- Fee estimation logic (auto-calculation based on fee schedules)
- Fee waiver management (the `fee_waiver_requested` column exists in the migration but no waiver approval/denial workflow was found)
- Payment status transitions and invoice generation
- An "Update Fee Estimate" button in the Request Detail UI's fee panel

The frontend `RequestDetail.tsx` loads and displays fees and has an inline fee-add form, but the broader fee workflow is incomplete.

**Corrected status: PARTIAL** (CRUD works; estimation, waivers, and full payment lifecycle not built)

### 3.3 Dashboard Filtering / Requests Page (gap list says DONE — actually PARTIAL)

The gap list says "Filter support in Requests page: DONE." The Requests page has a status filter dropdown, but the canonical spec (Section 7.4) requires five filter dropdowns: Status, Assigned To, Department, Priority, and Date Range. Only status filtering was confirmed. Pagination controls were also not found.

**Corrected status: PARTIAL** (status filter exists; four additional filters and pagination not built)

---

## 4. Staff UI Gaps Against the Canonical Spec

The gap list's "needs verification" language on the 11 staff pages is fair in spirit, but source inspection reveals concrete misses. These are not "maybe" items — the code does not contain them.

### Dashboard (Section 7.2)

| Feature | Spec Requires | Repo Has |
|---------|--------------|----------|
| Priority stat cards (4) | Open Requests, Overdue, Avg Response, Deadline Compliance | Has Overdue and Compliance; also shows Registered Users, Audit Log Entries, System Version (not in spec) |
| Service health row | Database, LLM Engine, Task Queue | **Present** — `ServiceIndicator` component for PostgreSQL, Ollama, Redis |
| Recent activity timeline | Last 10 events across all requests | **Missing** |
| Requests by status | Mini bar chart or stacked badges | **Missing** |
| Approaching deadlines | Next 5 with days remaining | **Missing** |
| Quick actions | New Request, Search Records, Export Audit Log | Has quick action buttons but Export Audit Log not confirmed |
| Coverage gap indicators | Section 12 gap map | **Missing** |

### Search (Section 7.3)

| Feature | Spec Requires | Repo Has |
|---------|--------------|----------|
| Normalized scores | 0-100% with progress bar | **Present** — `normalizeScore()` with colored progress bar and percentage |
| AI Summary panel | "Generate AI summary" checkbox with source citations | Checkbox present; citation rendering in summary card **not confirmed** |
| Department filter | Filter by department | **Missing** — only file_type filter exists |
| Export results | Export button | **Missing** |
| Empty state guidance | Example searches, prominent search bar | `EmptyState` component imported; specifics need visual verification |

### Requests (Section 7.4)

| Feature | Spec Requires | Repo Has |
|---------|--------------|----------|
| Priority stat cards | Overdue, Due This Week, In Review, Total Open | Needs visual verification |
| Full filter bar | Status, Assigned To, Department, Priority, Date Range | Status filter only |
| Priority indicators | Red urgent, normal, expedited | **Not confirmed** |
| Pagination | Previous/Next with page count | **Missing** |
| "No deadline set" text | Replace "None" | Needs verification |

### Request Detail (Section 7.5)

| Feature | Spec Requires | Repo Has |
|---------|--------------|----------|
| Timeline panel | Chronological events from `request_timeline` | **Present** — loads from API and renders |
| Messages panel | Internal/requester toggle | **Present** — sends messages with `is_internal` toggle |
| Fee tracking panel | Display, add, update estimates | **Present** — loads fees, has inline add form |
| Two-column layout | 65%/35% split | Uses `lg:grid-cols-3` with `lg:col-span-2` (≈67%/33%) — close enough |
| Workflow actions | Status transitions with buttons | **Present** — `WORKFLOW_ACTIONS` mapping with status-appropriate buttons |
| Generate Response Letter | Button triggering LLM | **Missing from frontend** (backend endpoint exists) |
| Response letter editor | Rich text editing of draft | **Missing** (no rich text editor library in deps) |
| Document display names | Original filenames, not UUIDs | Needs verification |

### Exemptions (Section 7.6)

| Feature | Spec Requires | Repo Has |
|---------|--------------|----------|
| Tab bar | Flags for Review, Rules, Audit History | Two tabs present (Rules, Flags for Review); **Audit History tab missing** |
| Flag review workflow | Accept/Reject/View Context table | `Flags for Review` tab exists with empty state handling |
| "No flags reviewed yet" | Replace misleading "Acceptance Rate: 0.0%" | **Present** — implemented correctly (lines 162-164) |
| Rule test modal | Test input for rule validation | **Missing** |

### Sources (Section 7.7)

| Feature | Spec Requires | Repo Has |
|---------|--------------|----------|
| Card grid layout | Cards not table | **Present** — `SourceCard` component in grid layout |
| Guided setup wizard | 3-step: path, schedule, department | Simple form with name + path inputs; **not a 3-step wizard** |
| Test Connection | Button per source | **Missing** |
| Integration placeholders | SharePoint, Database, API "coming soon" | **Present** — `ComingSoonCard` component with phase labels |

### Ingestion (Section 7.8)

| Feature | Spec Requires | Repo Has |
|---------|--------------|----------|
| Clean filenames | Original names, not UUIDs | **Present** — `stripUuidPrefix()` function strips UUID prefixes |
| Relative timestamps | "3 hours ago" | **Present** — `timeAgo()` function with minute/hour/day formatting |
| Progress indicators | Progress bar during active processing | **Not confirmed** |
| Retry for failed | Re-ingest button | **Not confirmed** |

### Users (Section 7.9)

| Feature | Spec Requires | Repo Has |
|---------|--------------|----------|
| Department column | Department assignment visible | Shows department_id as truncated UUID — **not a readable department name** |
| User edit view | Edit modal/page | **Missing** |
| Deactivate button | Per-user action | **Missing** |

### Missing Pages

| Page | Spec Section | Status |
|------|-------------|--------|
| **Settings** | 7.10 (System Configuration) | **No page exists.** No `Settings.tsx`, no route, no sidebar entry |
| **Audit Log viewer** | 7.11 (Audit) | **No page exists.** Backend audit router exists but no frontend |

---

## 5. Backend Gaps Not in the Gap List

These were found during repo inspection but are not called out (or are understated) in the gap list.

- **Notification calls not wired into status transitions.** The canonical spec (Section 7.1) says every status change triggers a notification if a template exists. The request router writes timeline and audit entries on transition but does not call the notification service. This is a compliance gap.
- **README contradicts code.** The README states SMTP email delivery is not yet implemented. The `notifications/smtp_delivery.py` module exists. Either the code is scaffolding or the README is stale — either way, the repo tells two stories.
- **Context manager not used by response letter generation.** The `generate_response_letter` endpoint in `requests/router.py` does its own inline prompt assembly. The `context_manager.py` module exists separately but doesn't appear to be imported or used anywhere. These need to be connected.
- **No notification template seed data.** `seed_templates.py` seeds 5 compliance/disclosure templates. The 7 notification event templates from Section 8.4 have no seed script.
- **Tier 1 regex pattern completeness unverified.** `exemptions/patterns.py` (205 lines) exists, but verification against the full spec pattern set (SSN, credit cards with Luhn, bank account/routing numbers, state-specific driver's licenses) requires running the tests or manually cross-referencing every pattern.

---

## 6. Summary: Corrected Status Table

| # | Item | Gap List Says | Corrected Status | Key Evidence |
|---|------|--------------|-----------------|--------------|
| 0 | Phase 0: Design Foundation | COMPLETE | **COMPLETE** | Confirmed |
| 1.1–1.11 | Phase 1: Staff UI (11 pages) | "Need verification" | **PARTIAL** — files exist, multiple concrete gaps per page (see Section 4) | Source inspection |
| 2.1 | Context Manager | MISSING | **PARTIAL** | `llm/context_manager.py` exists (199 lines); no model_registry integration |
| 2.2 | Response letter generation | PARTIAL (model only) | **Backend DONE, Frontend MISSING** | Full Ollama endpoint + approval workflow; no UI button or rich text editor |
| 2.3 | Onboarding LLM interview | PARTIAL | **PARTIAL** (agreed) | CRUD router only; no LLM-guided adaptive interview logic |
| 2.4 | Tier 1 regex | UNKNOWN | **UNKNOWN** (agreed) | 205-line patterns file exists; completeness unverified |
| 2.5 | Fee tracking | DONE | **PARTIAL** | CRUD + line items work; estimation, waivers, payment lifecycle missing |
| 2.6 | Audit retention cleanup | PARTIAL | **DONE** | Celery Beat daily task with configurable retention |
| 2.7 | Notification template seeds | UNKNOWN | **MISSING** | Seed script is for compliance templates, not notification events |
| 2.8 | Status transition side effects | UNKNOWN | **PARTIAL** | Timeline + audit written; notification dispatch not wired in |
| — | SMTP / notification service | DONE | **PARTIAL** | Code exists; not wired into transitions; README says not implemented |
| — | Dashboard filtering | DONE | **PARTIAL** | Status filter only; spec requires 5 filters + pagination |
| — | Settings page | Not mentioned | **MISSING** | No file, no route |
| — | Audit Log page | Not mentioned | **MISSING** | No frontend page (backend router exists) |
| — | Skip-to-content | MISSING | **MISSING** (confirmed) | Zero grep matches |
| — | Public RBAC role | NOT STARTED | **PARTIAL** | Role exists in enum; no routes or enforcement |
| 3.x | Phase 3 (v1.1) | NOT STARTED | **NOT STARTED** (confirmed) | No code |
| 4.x | Phase 4 (v2.0) | NOT STARTED | **NOT STARTED** (confirmed) | No code |

---

## 7. Revised Critical Path for v1.0

Based on the corrected statuses above, the blocking items for a functional staff workbench are:

1. **Wire context manager into response letter generation** — both pieces exist independently; connect them.
2. **Add model-registry integration to context manager** — spec requires model-aware budgeting.
3. **Build response letter UI** — "Generate Response Letter" button + rich text editor on Request Detail page.
4. **Wire notification dispatch into status transitions** — compliance requirement per Section 7.1.
5. **Seed the 7 notification event templates** — received, clarification, assigned, deadline approaching, deadline overdue, records ready, request closed.
6. **Onboarding LLM interview logic** — adaptive question flow, catalog cross-referencing, gap map generation.
7. **Add skip-to-content link** — WCAG 2.2 AA hard requirement.
8. **Build Settings page and Audit Log page** — two pages the spec requires that have no frontend.
9. **Complete Requests filter bar** — 4 missing filters (Assigned To, Department, Priority, Date Range) + pagination.
10. **Complete Dashboard widgets** — recent activity, approaching deadlines, requests-by-status, coverage gaps.
11. **Reconcile README with code** — SMTP delivery claim needs to match reality.
