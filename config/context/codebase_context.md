# Proof2Pay Codebase Context

*Last updated: February 2026*
*Update this file after each development sprint so agents have an accurate picture.*

## Phase 1 Status: COMPLETE ✅

### Database Schema (PostgreSQL + Alembic)

**Core Tables:**
- `organizations` — NPOs and Agencies. Fields: id, name, type (NPO/Agency), tenant_id
- `contracts` — Agreement between an NPO and Agency for a fiscal year. Fields: id, npo_org_id, agency_org_id, fiscal_year, start_date, end_date, total_budget, status, tenant_id
- `budget_categories` — Per-contract categories. Fields: id, contract_id, name, code, allocated_amount, parent_category_id, tenant_id
- `invoices` — Monthly submissions. Fields: id, contract_id, period_start, period_end, status (draft/ai_review/npo_review/submitted/agency_review/approved/rejected), submitted_at, submitted_by, tenant_id
- `line_items` — Individual expenses. Fields: id, invoice_id, budget_category_id, description, amount, expense_date, status, tenant_id
- `source_documents` — Uploaded files. Fields: id, filename, mime_type, file_hash, upload_timestamp, uploader_id, storage_ref, tenant_id
- `line_item_documents` — Join table linking line items to source documents
- `audit_events` — Append-only log. Fields: id, event_type, actor_id, timestamp, entity_type, entity_id, payload (JSONB), tenant_id
- `entity_registry` — Per-contract entity records. Fields: id, contract_id, stable_id (e.g. EMP_00042), canonical_name, aliases (JSONB), role, title, department, annual_salary, hourly_rate, confidence_score, last_matched_at, tenant_id

**Identity/Auth Tables:**
- `users` — Platform users. Fields: id, email, name, external_auth_id
- `user_tenant_roles` — Cross-tenant identity mapping. Fields: user_id, tenant_id, contract_id, role (npo_user/npo_admin/agency_reviewer/agency_admin/platform_admin)

**Key Constraints:**
- All tables have tenant_id for future per-tenant database migration
- All queries are tenant-scoped via middleware
- Entity Registry is scoped per contract (not per organization)
- Audit events are append-only (no UPDATE or DELETE)

### Rules Engine

**Rule Set Schema (JSON/YAML per agency, versioned):**
Each rule has: rule_id, entity_scope, category_scope, condition_type (deterministic/llm_assisted), condition_logic, flag_severity (hard_fail/soft_flag/confirmation), message_template

**Deterministic Evaluator (Complete):**
Handles: amount matching, date range checks, missing required fields, budget limit calculations, required documentation checks. These produce hard fails without LLM involvement.

**LLM-Assisted Evaluation (Phase 2):**
Not yet built. Will handle: category classification, description matching, subjective judgment calls. Behind validate_line_item abstraction.

### API Layer (FastAPI)

**Endpoint Groups:**
- `/api/v1/contracts/` — CRUD for contracts and budget categories
- `/api/v1/invoices/` — Full lifecycle: create, update, submit_for_review, submit_to_agency, approve, reject
- `/api/v1/invoices/{id}/line-items/` — CRUD within invoice, link to documents
- `/api/v1/documents/` — Upload, metadata, link to line items
- `/api/v1/entities/` — Entity Registry CRUD, alias management, match confirmation
- `/api/v1/rules/` — Agency rule set CRUD with versioning
- `/api/v1/audit/` — Read-only query with filters

### Abstraction Interfaces

```python
# LLM Extraction — not yet implemented, interface defined
def extract_document(segment: DocumentSegment, schema: ExtractionSchema) -> ExtractionResult

# LLM Validation — not yet implemented, interface defined
def validate_line_item(item: LineItem, segment: DocumentSegment, rules: list[Rule], entity_ctx: EntityContext) -> ValidationResult

# OCR/Doc Parsing — not yet implemented, interface defined
def parse_document(file_bytes: bytes, mime_type: str) -> ParsedDocument

# PII Detection — not yet implemented, interface defined
def detect_pii(text: str) -> list[PIIEntity]

# File Storage — IMPLEMENTED against local filesystem
def upload(file: bytes, metadata: dict) -> DocumentRef
def get(ref: DocumentRef) -> bytes

# Auth — IMPLEMENTED against Auth0 free tier via OIDC
```

### Test Suite
- pytest with fixtures for test data
- Unit tests for deterministic rule evaluation
- Unit tests for entity matching algorithms (Jaro-Winkler)
- Integration tests for API endpoints
- All passing

## Phase 2 Status: IN PROGRESS 🔨

### Currently Building:
1. Document segmentation (Pass 1) — structural analysis + amount/date matching
2. Structured extraction (Pass 2) — via extract_document abstraction, OpenAI API dev
3. PII handling pipeline — Presidio → Entity Registry matching → redaction
4. Compliance validation service — adversarial second pass via validate_line_item
5. Invoice assembly — mapping extracted data to agency schema

### Known Limitations / Open Questions:
- Budget categories assume 1:1 with line items (no split-funding model yet)
- Entity Registry doesn't handle subcontractors or partner org employees
- Rules engine can't express cross-line-item rules (e.g., "total personnel < 60% of budget")
- No amendment/budget modification workflow yet
- Document segmentation approach not yet validated on real multi-page documents
