# B2B Document Automation

**Zero-disk B2B invoice and document processing pipeline — ingest, parse, review, and ledger with AI-assisted extraction.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)](https://github.com/sajidkhan001/B2BInvoiceAutomation)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Automate your B2B document workflows from email to Google Sheets — entirely on your own machine, no external database required.

Most automation platforms store your documents and extracted data in a cloud database, charging monthly fees and creating a data-leave boundary you may not want. This application is different: everything stays on-device. Documents are parsed in-memory, secrets are held in your Windows Credential Manager, preferences live in local AppData, and the only outbound connection is to Google Sheets (or your IMAP server). No database to provision, no monthly bill, no third party holding your B2B data.

Designed for Windows desktop deployment, it ingests invoices, credit notes, purchase orders, delivery notes, and receipts from IMAP or Gmail, parses them in-memory with pdfplumber, validates extracted fields with Pydantic, optionally refines low-confidence extractions via OpenAI or Anthropic, and writes structured records to a Google Sheets ledger — without ever writing source binaries to disk.

---

## Table of Contents

- [Why This Exists](#why-this-exists)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Data Flow](#data-flow)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Configuration](#configuration)
  - [Environment Variables](#environment-variables)
  - [Desktop Settings](#desktop-settings)
- [Supported Document Types](#supported-document-types)
- [AI Providers](#ai-providers)
- [Email Ingestion](#email-ingestion)
  - [Generic IMAP](#generic-imap)
  - [Gmail OAuth](#gmail-oauth)
- [Google Sheets Ledger](#google-sheets-ledger)
- [Desktop Application](#desktop-application)
- [Security & Privacy](#security--privacy)
- [Build & Package](#build--package)
- [Testing](#testing)
- [Development](#development)

---

## Why This Exists

B2B document processing in small-to-medium businesses often means:
- Manually downloading PDF attachments from email
- Copying figures into spreadsheets
- Juggling multiple mailboxes, formats, and naming conventions
- No audit trail, no duplicate detection, no confidence tracking

This project solves those problems with a Windows-native desktop app that:
- Polls IMAP or Gmail inboxes for attachments automatically
- Classifies and extracts fields from PDFs using heuristic + AI extraction
- Routes low-confidence documents to a human review queue
- Writes verified records to Google Sheets with full idempotency and audit logging
- Guarantees **zero binary retention** — original documents are never written to disk

---

## Key Features

| Category | Capabilities |
|----------|-------------|
| **Ingestion** | Generic IMAP (SSL), Gmail API v1 (OAuth), multiple concurrent mail sources |
| **Security** | Magic-byte sniffing, extension allow-listing (PDF/JPEG/PNG/TIFF/HEIC), ClamAV clamd INSTREAM scanning (fail-closed), in-memory wiping |
| **Parsing** | pdfplumber text + table extraction, multi-page table reconstruction, regex field extraction |
| **Classification** | Invoice, credit note, purchase order, delivery note/goods receipt, receipt, unknown |
| **AI Fallback** | OpenAI (GPT models) and Anthropic (Claude models) for low-confidence field correction |
| **Confidence Scoring** | 6-component breakdown (base, document type, required fields, table continuity, arithmetic, source quality) |
| **Routing** | Autonomous (≥ threshold), needs review (< threshold), rejected (security/parse failure), duplicate (idempotency) |
| **Ledger** | Google Sheets with 5 tabs (Documents, LineItems, AuditEvents, Rejects, Index), formula-injection protection, append-only |
| **Desktop UI** | PySide6 interface with Dashboard, Mail Sources, Sheets, AI Models, Review Queue, Logs, Security tabs |
| **Scheduling** | Configurable polling interval (10–86400s), thread-based, pause/resume/stop |
| **Secrets** | Windows Credential Manager via keyring for passwords, OAuth tokens, API keys |
| **Packaging** | PyInstaller build scripts, Start Menu & desktop shortcuts, clean uninstall |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Email Sources                               │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│   │  IMAP Server  │  │  Gmail API   │  │  ...more     │        │
│   └──────┬───────┘  └──────┬───────┘  └──────┬───────┘        │
│          │                 │                 │                  │
│          └────────┬────────┘─────────────────┘                  │
│                   │                                              │
│          ┌────────▼────────┐                                     │
│          │  BoundedMemory  │  SHA256 hashing, size enforcement,  │
│          │    Manager      │  inflight byte budget (512 MB max)  │
│          └────────┬────────┘                                     │
│                   │                                              │
│          ┌────────▼────────┐                                     │
│          │    Security     │  Magic-byte validation, extension   │
│          │    Validation   │  allow-list, ClamAV clamd scan      │
│          └────────┬────────┘                                     │
│                   │                                              │
│          ┌────────▼────────┐                                     │
│          │    Parsing      │  pdfplumber (isolated process),     │
│          │    Engine       │  regex extraction, classification   │
│          └────────┬────────┘                                     │
│                   │                                              │
│          ┌────────▼────────┐                                     │
│          │  AI Fallback    │  OpenAI / Anthropic field           │
│          │  (optional)     │  correction, +0.10 confidence       │
│          └────────┬────────┘                                     │
│                   │                                              │
│          ┌────────▼────────┐                                     │
│          │   Confidence    │  ≥ 0.90 → autonomous               │
│          │    Router       │  < 0.90 → human review              │
│          └──┬──────────┬──┘                                     │
│             │          │                                         │
│    ┌────────▼──┐  ┌───▼────────┐                                │
│    │  Google   │  │   Review   │  Desktop queue for human       │
│    │  Sheets   │  │   Queue    │  approve / reject decisions    │
│    └───────────┘  └────────────┘                                │
└─────────────────────────────────────────────────────────────────┘
```

## Data Flow

```
Email arrives (IMAP / Gmail)
  │
  ├─ BoundedMemoryManager.create_envelope()
  │   • Reads attachment in chunks, computes SHA256
  │   • Reserves byte budget, sets 15-minute TTL
  │   • Returns IngestionEnvelope (unpicklable, in-memory only)
  │
  ├─ validate_envelope()
  │   • Checks file size ≤ B2B_MAX_FILE_MB (default 25 MB)
  │   • Sniffs magic bytes: %PDF, \xff\xd8\xff, \x89PNG, TIFF, HEIC
  │   • Rejects dangerous extensions: .exe, .zip, .docm, etc.
  │
  ├─ ClamAVScanner.scan()
  │   • Sends payload via clamd INSTREAM protocol (1 MB chunks)
  │   • Fail-closed: scanner unavailable → rejection
  │   • Dev bypass: B2B_ALLOW_UNSCANNED_DEV=true
  │
  ├─ ParserRunner.parse()
  │   • Runs in isolated ProcessPoolExecutor (45s timeout)
  │   • pdfplumber: per-page text + table extraction
  │     • Lines strategy + text strategy
  │     • Multi-page table reconstruction (header dedup, continuation merge)
  │   • classify_document(): keyword matching → document type
  │   • Regex extraction: document number, PO, dates, currency, amounts, parties
  │   • Line items: from tables (primary) or regex (fallback)
  │   • Semantic validation: missing fields, arithmetic (subtotal + tax ≈ total)
  │   • Confidence scoring: 6-component breakdown [0, 1]
  │
  ├─ ProviderAIFallback.improve()  [if configured & low confidence]
  │   • Sends current extraction to OpenAI / Anthropic
  │   • Requests JSON corrections for key fields only
  │   • Applies corrections, boosts confidence +0.10 (capped at 0.89)
  │   • Graceful failure → original extraction preserved
  │
  ├─ Confidence Router
  │   • ≥ 0.90 + no validation errors → autonomous
  │   • < 0.90 or validation errors → review queue
  │   • Security failure → rejected
  │   • Idempotency key collision → duplicate (skipped)
  │
  ├─ GoogleSheetsLedger.write()
  │   • 5 tabs: Documents, LineItems, AuditEvents, Rejects, Index
  │   • Formula-injection neutralization (leading = + - @ → ' prefixed)
  │   • Idempotency check via hidden Index tab
  │   • Append-only, never modifies existing rows
  │
  └─ envelope.wipe()  [finally block]
      • Zero-fills every byte, clears bytearray, releases budget
```

---

## Quick Start

### Prerequisites
- Python 3.11 – 3.14
- Windows (primary target; Linux/macOS partial support)
- ClamAV with `clamd` running (recommended) or `B2B_ALLOW_UNSCANNED_DEV=true` for development

### Installation

```powershell
# Create virtual environment
py -3.11 -m venv .venv

# Activate (PowerShell)
.\.venv\Scripts\Activate.ps1
# Or CMD: .venv\Scripts\activate.bat

# Upgrade pip and install
python -m pip install -U pip
python -m pip install -e .[dev]
```

### Run Tests

```powershell
python -m pytest
```

### Launch Desktop App

```powershell
b2bdoc-desktop
# or
python -m b2bdoc.desktop.main
```

### Run One IMAP Poll Pass

```powershell
b2bdoc imap-once
```

### Diagnostics

```powershell
b2bdoc doctor
```

---

## CLI Reference

The `b2bdoc` CLI entry point provides three commands:

| Command | Description |
|---------|-------------|
| `b2bdoc doctor` | Print runtime configuration: file limits, confidence threshold, ClamAV status, IMAP configuration, Google Sheets setup |
| `b2bdoc imap-once` | Run a single IMAP poll pass — fetch unseen attachments, process through pipeline, print results |
| `b2bdoc desktop` | Launch the PySide6 desktop GUI (also available as `b2bdoc-desktop`) |

---

## Configuration

### Environment Variables

All settings are prefixed with `B2B_`. The desktop app stores most settings in a JSON config file and secrets in Windows Credential Manager; environment variables serve as CLI/headless fallback.

#### File & Processing Limits

| Variable | Default | Description |
|----------|---------|-------------|
| `B2B_MAX_FILE_MB` | `25` | Maximum individual attachment size (MB) |
| `B2B_MAX_PAGES` | `50` | Maximum PDF pages to parse |
| `B2B_MAX_INFLIGHT_MB` | `512` | Total in-flight memory budget (MB) |
| `B2B_CONFIDENCE_THRESHOLD` | `0.90` | Minimum confidence for autonomous processing |
| `B2B_PARSER_WORKERS` | `max(1, min(4, CPU-1))` | Number of parser worker processes |
| `B2B_PARSER_TIMEOUT_SECONDS` | `45` | Parser process timeout (seconds) |
| `B2B_POLL_INTERVAL_SECONDS` | `60` | Scheduler poll interval (seconds) |

#### ClamAV Antivirus

| Variable | Default | Description |
|----------|---------|-------------|
| `B2B_CLAMAV_HOST` | `127.0.0.1` | ClamAV clamd host |
| `B2B_CLAMAV_PORT` | `3310` | ClamAV clamd port |
| `B2B_CLAMAV_TIMEOUT_SECONDS` | `15` | ClamAV socket timeout |
| `B2B_ALLOW_UNSCANNED_DEV` | `false` | Bypass ClamAV (development only — never use in production) |
| `B2B_ALLOW_HEIC` | `false` | Allow HEIC image attachments |

#### IMAP Source

| Variable | Default | Description |
|----------|---------|-------------|
| `B2B_IMAP_HOST` | — | IMAP server hostname |
| `B2B_IMAP_PORT` | `993` | IMAP SSL port |
| `B2B_IMAP_USER` | — | IMAP username |
| `B2B_IMAP_PASSWORD` | — | IMAP password (store in Windows Credential Manager for desktop use) |
| `B2B_IMAP_MAILBOX` | `INBOX` | Mailbox to search |
| `B2B_IMAP_SEARCH` | `UNSEEN` | IMAP search criterion |

#### Google Sheets (CLI / Service Account)

| Variable | Default | Description |
|----------|---------|-------------|
| `B2B_GOOGLE_SHEET_ID` | — | Google Sheets spreadsheet ID |
| `B2B_GOOGLE_SERVICE_ACCOUNT_FILE` | — | Path to service account JSON key |

The desktop app uses OAuth instead (see [Google Sheets Ledger](#google-sheets-ledger)).

#### AI Fallback

| Variable | Default | Description |
|----------|---------|-------------|
| `B2B_AI_PROVIDER` | — | `openai` or `anthropic` |
| `B2B_AI_MODEL` | — | Model ID (e.g., `gpt-4o`, `claude-sonnet-4-20250514`) |
| `B2B_AI_FALLBACK_ENABLED` | `false` | Enable AI fallback for low-confidence documents |

API keys are stored in Windows Credential Manager via the desktop UI (see [AI Providers](#ai-providers)).

### Desktop Settings

Stored as JSON in `%APPDATA%\B2BDocAutomation\config.json`:

| Setting | Default | Description |
|---------|---------|-------------|
| `poll_interval_seconds` | `60` | Poll interval |
| `start_with_windows` | `false` | Auto-start on Windows login |
| `close_to_tray` | `true` | Minimize to tray on window close |
| `mail_sources` | `[]` | List of mail source configurations |
| `sheets.spreadsheet_id` | `""` | Google Sheets ID |
| `sheets.oauth_client_secrets_file` | `""` | OAuth client JSON path |
| `ai.fallback_enabled` | `true` | AI fallback toggle |
| `ai.provider` | `"openai"` | AI provider |
| `ai.model` | `""` | AI model ID |
| `security.allow_unscanned_dev` | `false` | ClamAV bypass |
| `security.clamav_host` | `"127.0.0.1"` | ClamAV host |
| `security.clamav_port` | `3310` | ClamAV port |

Secrets (IMAP passwords, OAuth tokens, AI API keys) are stored exclusively in **Windows Credential Manager** via the `keyring` library — never in config files or environment variables.

Each mail source in `mail_sources` supports:

| Field | Default | Description |
|-------|---------|-------------|
| `kind` | `"imap"` | `"imap"` or `"gmail"` |
| `display_name` | `"Mail source"` | Human-readable label |
| `enabled` | `true` | Enable/disable without removing |
| `imap_host` | `""` | IMAP server |
| `imap_port` | `993` | IMAP port |
| `imap_user` | `""` | IMAP username |
| `imap_mailbox` | `"INBOX"` | Mailbox folder |
| `imap_search` | `"UNSEEN"` | IMAP search filter |
| `gmail_client_secrets_file` | `""` | Gmail OAuth JSON path |
| `gmail_query` | `"has:attachment is:unread"` | Gmail API search query |

---

## Supported Document Types

| Type | Detection | Expected Fields |
|------|-----------|----------------|
| **Invoice** | Contains "invoice" or "amount due" | Document number, supplier, customer, issue date, due date, line items, subtotal, tax, total |
| **Credit Note** | Contains "credit note" or "credit memo" | Document number, supplier, customer, issue date, line items, total |
| **Purchase Order** | Contains "purchase order" or "po #" | PO number, supplier, issue date, line items, total |
| **Delivery Note** | Contains "delivery note", "goods receipt", or "packing slip" | Document number, supplier, date, line items |
| **Receipt** | Contains "receipt" (without "invoice") | Store name, date, line items, total |
| **Unknown** | No keywords matched | Best-effort extraction |

### Field Extraction Strategy

Each field is extracted through a cascade:
1. **Labeled lookup**: scan text for field labels (`Invoice #`, `PO Number`, `Date:`, etc.)
2. **Regex extraction**: pattern matching for document numbers, PO numbers, dates (9 format variants), currencies, monetary amounts
3. **Table extraction**: line items from PDF tables via pdfplumber with multi-page reconstruction
4. **AI correction** (optional): OpenAI/Anthropic refines low-confidence fields

### Confidence Scoring Breakdown

| Component | Weight | Basis |
|-----------|--------|-------|
| `base_extraction` | 0.35 | Baseline |
| `document_type` | 0.10 | 0 if unknown |
| `required_fields` | 0.25 | Proportion of required fields present |
| `table_continuity` | 0.15 | Table extraction quality |
| `arithmetic_schema` | 0.10 | Subtotal + tax ≈ total (within $0.05) |
| `source_quality` | 0.05 | Fixed |

---

## AI Providers

Supported as low-confidence extraction fallback. AI never receives raw document binaries — only the structured extraction result.

### Configuration

| Provider | API Base | Auth |
|----------|----------|------|
| **OpenAI** | `https://api.openai.com/v1` | `Authorization: Bearer <key>` |
| **Anthropic** | `https://api.anthropic.com/v1` | `x-api-key: <key>` |

### Behavior

- Triggers only for `application/pdf` documents
- Only when confidence < threshold or validation errors exist
- Sends current extraction fields (document number, dates, amounts) for JSON correction
- Applies corrections to a deep copy; original preserved on API failure
- Boosts confidence by +0.10 (capped at 0.89 — never bypasses human review automatically)
- Adds warning: `"AI fallback used: {provider}"`
- API timeout: 45 seconds

### Querying Available Models

The desktop UI validates API keys and fetches available models on demand. Alternatively, test via CLI:

```powershell
# Check your key works with an API call
curl -H "Authorization: Bearer $env:OPENAI_API_KEY" https://api.openai.com/v1/models
```

---

## Email Ingestion

### Generic IMAP

Connects via `IMAP4_SSL` (port 993). Configured through:

- **CLI**: `B2B_IMAP_HOST`, `B2B_IMAP_USER`, `B2B_IMAP_PASSWORD` env vars
- **Desktop**: Mail Sources tab with password stored in Windows Credential Manager

The ingestor:
1. Selects the configured mailbox (default `INBOX`)
2. Searches with configured criterion (default `UNSEEN`)
3. Iterates message parts, extracts attachments
4. Creates `IngestionEnvelope` per attachment with source_locator `imap:{uid}:part:{index}:{filename}`
5. Passes each envelope through the pipeline

### Gmail OAuth

Uses the Gmail API v1 with OAuth 2.0 (read-only scope: `gmail.readonly`). Configured through the desktop UI:

1. Provide a Gmail OAuth client secrets JSON file
2. Click "Connect Gmail OAuth" — browser flow completes authentication
3. Token saved to Windows Credential Manager with automatic refresh

Default query: `has:attachment is:unread`

---

## Google Sheets Ledger

The ledger organizes data across 5 tabs:

### Tab Structure

| Tab | Columns | Purpose |
|-----|---------|---------|
| **Documents** | 18 | Written timestamp, idempotency key, source hash, locator, status, document type, number, PO number, dates, supplier, customer, currency, amounts, confidence, validation errors, actor |
| **LineItems** | 11 | Written timestamp, idempotency key, source hash, line number, description, quantity, unit price, tax, total, confidence, flags |
| **AuditEvents** | 9 | Event timestamp, event ID, source hash, locator, event type, status, confidence, actor, details |
| **Rejects** | 5 | Timestamp, source hash, locator, reason, actor |
| **Index** | 4 (hidden) | Idempotency key, source hash, written timestamp, status |

### Key Behaviors

- **Append-only**: No existing rows are ever modified or deleted
- **Idempotency**: Keyed as `{source_hash}:{document_type}:{document_number}` — checked against the Index tab
- **Formula injection protection**: Values starting with `=`, `+`, `-`, or `@` are prefixed with `'`
- **Discovery caching disabled**: `cache_discovery=False` avoids local discovery-cache writes

### Connection Paths

| Method | Credentials | Use Case |
|--------|-------------|----------|
| **Desktop OAuth** | `InstalledAppFlow` via browser | Desktop UI with user interaction |
| **Service Account** | `B2B_GOOGLE_SERVICE_ACCOUNT_FILE` env var | CLI / headless automation |

---

## Desktop Application

Built with **PySide6 (Qt)**. Presents a tabbed interface for the entire workflow.

### Tabs

1. **Dashboard** — Start, pause, resume, or stop the automation scheduler; exit the application
2. **Mail Sources** — Add/edit IMAP or Gmail sources; connect Gmail OAuth; enable/disable sources
3. **Google Sheets** — Configure spreadsheet ID; connect Google Sheets OAuth
4. **AI Models** — Toggle AI fallback; select provider; enter API key; fetch and choose model
5. **Review Queue** — List documents needing human review; approve or reject
6. **Processing Logs** — Scrollback of scheduler events and processing results
7. **Security** — Poll interval, auto-start, close-to-tray, ClamAV settings, dev bypass

### System Tray

- Closing the window minimizes to tray (configurable)
- Tray tooltip shows automation status
- Context menu: Open, Pause/Resume, Exit
- Notifications for errors (Critical) and new review items (Warning)

### Background Scheduling

The scheduler runs on a daemon thread. When active:
- Polls every configured interval (default 60s)
- Processes each mail source in sequence
- Appends results to the ledger or review queue
- Sends tray notifications for actionable events

---

## Security & Privacy

### Binary Non-Retention (Core Design Principle)

Original PDFs and images are **never** written to:
- Local disk (including temp directories)
- Log files or console output
- Google Sheets cells or attachments
- Cache or crash dumps
- AI provider payloads (only structured extraction text is sent)

Only the following are retained:
- **SHA256 hash** of the source binary (for deduplication and audit)
- **Source metadata** (mailbox, UID, filename, content type)
- **Structured extraction fields** (document number, dates, amounts, line items, etc.)
- **Confidence scores** and **confidence breakdowns**
- **Processing decisions** (autonomous, needs review, rejected, duplicate)
- **Audit events** (timestamp, action, actor)

### Attachment Validation

**Extension blocklist** (20 dangerous types rejected):
`.exe .dll .bat .cmd .com .js .vbs .ps1 .zip .7z .rar .tar .gz .doc .docx .xls .xlsx .ppt .pptx`

**Macro-enabled extensions** (explicitly rejected with specific error):
`.docm .xlsm .pptm`

**Magic-byte allow-list**:

| Magic Bytes | Media Type | Conditional |
|-------------|------------|-------------|
| `%PDF` (offset 0) | `application/pdf` | Always |
| `\xff\xd8\xff` | `image/jpeg` | Always |
| `\x89PNG\r\n\x1a\n` | `image/png` | Always |
| `II*\x00` / `MM\x00*` | `image/tiff` | Always |
| `ftyp` + heic/heix/hevc/hevx brand | `image/heic` | `B2B_ALLOW_HEIC=true` |

### Antivirus (ClamAV)

- **Protocol**: clamd INSTREAM (`zINSTREAM\0`)
- **Chunk size**: 1 MB
- **Behavior**: Fail-closed — if `clamd` is unreachable, the document is rejected with `SCANNER_UNAVAILABLE`
- **Development bypass**: Set `B2B_ALLOW_UNSCANNED_DEV=true` — do not use in production

### Memory Management

- `MemoryBuffer.wipe()` overwrites every byte with `\x00`, clears the `bytearray`, and invokes a release callback
- `IngestionEnvelope.wipe()` delegates to the internal buffer
- Pipeline `process()` guarantees `envelope.wipe()` in a `finally` block
- `IngestionEnvelope.__getstate__` raises `TypeError` — envelopes cannot be pickled, preventing accidental serialization or IPC leaks
- `BoundedMemoryManager` tracks total inflight bytes and rejects new envelopes when the budget is exceeded

### Forensic Considerations

This project avoids application-level binary persistence. For strict forensic zero-disk behavior, additional OS hardening is recommended:
- Encrypted disk (BitLocker)
- Restricted temporary paths
- Disabled crash dumps where policy requires
- Appropriate pagefile policy
- Dedicated low-privilege Windows user account

### Secrets Management

| Secret Type | Storage | Access Pattern |
|-------------|---------|----------------|
| IMAP passwords | Windows Credential Manager | `keyring.get_password("b2bdoc-automation", "mail.imap.{id}.password")` |
| OAuth tokens | Windows Credential Manager | `keyring.get_password("b2bdoc-automation", "oauth.{name}.token_json")` |
| AI API keys | Windows Credential Manager | `keyring.get_password("b2bdoc-automation", "ai.{provider}.api_key")` |
| Non-secret preferences | AppData JSON | `%APPDATA%\B2BDocAutomation\config.json` |

---

## Build & Package

Build a standalone Windows executable with PyInstaller:

```powershell
# Full build (tests + package)
.\scripts\build_desktop.ps1

# Or step by step:
pip install -e .[dev]
PyInstaller --clean --noconfirm B2BInvoiceAutomation.spec
```

Install for the current user:

```powershell
.\scripts\install_desktop.ps1
```

This creates:
- `%LOCALAPPDATA%\Programs\B2B Invoice Automation\B2B Invoice Automation.exe`
- Start Menu shortcut under **B2B Invoice Automation**
- Desktop shortcut

Uninstall:

```powershell
.\scripts\uninstall_desktop.ps1
```

If PowerShell blocks local scripts, bypass execution policy:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_desktop.ps1
```

---

## Testing

The test suite covers security, pipeline routing, AI fallback, memory management, sheets integration, desktop settings, scheduling, and packaging.

```powershell
# Run all tests
python -m pytest

# Run with coverage
python -m pytest --cov=b2bdoc

# Run specific test file
python -m pytest tests/test_security.py -v

# Run single test
python -m pytest tests/test_pipeline.py::test_high_confidence_routes_to_ledger -v
```

### Test Areas

| File | Focus |
|------|-------|
| `tests/test_pipeline.py` | Autonomous routing, review routing, zero-disk guarantee |
| `tests/test_pipeline_ai.py` | AI fallback triggers, AI skip for high-confidence |
| `tests/test_security.py` | Extension rejection, magic-byte acceptance |
| `tests/test_table_fallback.py` | Multi-page table reconstruction |
| `tests/test_memory.py` | Envelope unpicklability, wipe behavior, budget enforcement |
| `tests/test_sheets.py` | Formula injection, duplicate suppression |
| `tests/test_ai_providers.py` | OpenAI/Anthropic model listing, auth error handling |
| `tests/test_desktop_settings.py` | Config round-trip, secret key naming |
| `tests/test_scheduler.py` | Review task collection, start/stop lifecycle |
| `tests/test_packaging.py` | Build assets, PyInstaller spec, install script |

---

## Development

### Project Structure

```
├── .env.example                     # Environment variable template
├── B2BInvoiceAutomation.spec        # PyInstaller build spec
├── pyproject.toml                   # Package metadata & dependencies
├── packaging/
│   └── desktop_launcher.py          # PyInstaller entry point
├── scripts/
│   ├── build_desktop.ps1            # Build executable
│   ├── install_desktop.ps1          # Install shortcuts
│   └── uninstall_desktop.ps1        # Clean removal
├── src/b2bdoc/
│   ├── cli.py                       # CLI: doctor, imap-once, desktop
│   ├── config.py                    # Settings dataclass from env vars
│   ├── models.py                    # Pydantic v2 data models
│   ├── memory.py                    # BoundedMemoryManager, IngestionEnvelope
│   ├── security.py                  # Magic-byte validation, ClamAV scanner
│   ├── parser.py                    # PDF extraction, classification, regex
│   ├── imap_ingest.py               # Generic IMAP ingestion
│   ├── pipeline.py                  # DocumentPipeline orchestrator
│   ├── sheets.py                    # Google Sheets ledger
│   ├── table_fallback.py            # Multi-page table reconstruction
│   ├── app.py                       # Entry point
│   ├── ai/
│   │   └── providers.py             # OpenAI / Anthropic fallback
│   ├── desktop/
│   │   ├── main.py                  # DesktopApp, controller, tray
│   │   ├── windows.py               # 7-tab PySide6 UI
│   │   ├── secrets.py               # Keyring secret store
│   │   └── settings_store.py        # JSON config + Windows Run key
│   ├── integrations/
│   │   └── google_oauth.py          # OAuth flow runner
│   ├── mail/
│   │   └── gmail_oauth.py           # Gmail API source
│   └── worker/
│       └── scheduler.py             # Background poll scheduler
└── tests/                           # Test suite (10 files)
```

### Key Design Decisions

1. **Process-isolated parsing**: The parser runs in a `ProcessPoolExecutor(max_workers=1)` with a configurable timeout. This prevents parser crashes (e.g., malformed PDFs) from affecting the main application and ensures hung documents are killed after 45 seconds.

2. **Bounded memory**: The `BoundedMemoryManager` tracks per-file and total-inflight bytes. Envelopes are created with an explicit byte reservation and auto-release on wipe. This prevents OOM conditions from large or numerous attachments.

3. **Fail-closed security**: If ClamAV `clamd` is unreachable, the document is rejected by default. This is safer than fail-open behavior that would process unscanned documents.

4. **Disjoint credential storage**: Secrets (passwords, OAuth tokens, API keys) use the OS-native Windows Credential Manager via `keyring`. Non-secret preferences use a plain JSON file in `%APPDATA%`. This prevents accidental secret exposure in config files or version control.

5. **Conservative AI confidence cap**: AI-boosted confidence never exceeds 0.89, ensuring that at least some human review is always possible before autonomous processing.

6. **Unpicklable envelopes**: `IngestionEnvelope.__getstate__` raises `TypeError`, preventing accidental serialization, persistence, or IPC transfer of binary document data.

### Adding a New Document Type

1. Add to `DocumentType` enum in `src/b2bdoc/models.py`
2. Add keyword detection in `classify_document()` in `src/b2bdoc/parser.py`
3. Add document-type-specific extraction logic if needed
4. Update `_semantic_validation()` for required fields
5. Update tests

### Adding a New AI Provider

1. Add provider configuration in `ProviderAIFallback` construction in `src/b2bdoc/ai/providers.py`
2. Add model listing endpoint, auth header, and API call format
3. Add provider selection option in desktop UI (`src/b2bdoc/desktop/windows.py`)
4. Update tests in `tests/test_ai_providers.py`

### Adding a New Mail Source Type

1. Implement a source class following the pattern of `IMAPIngestor` or `GmailOAuthSource`
2. Add source type to `MailSourceConfig.kind` validation in settings store
3. Add source configuration UI in the Mail Sources tab
4. Integrate with `DesktopController.poll_once()`
5. Update tests

---

## Dependencies

### Runtime

| Package | Minimum | Purpose |
|---------|---------|---------|
| `google-auth-oauthlib` | 1.2 | Google OAuth desktop flow |
| `google-api-python-client` | 2.130 | Google Sheets & Gmail APIs |
| `google-auth` | 2.29 | Credential management |
| `keyring` | 25.2 | Windows Credential Manager |
| `pdfplumber` | 0.11 | PDF text & table extraction |
| `pillow` | 10.3 | Image handling |
| `PySide6` | 6.7 | Qt desktop UI framework |
| `pydantic` | 2.7 | Data validation models |
| `requests` | 2.32 | AI provider HTTP client |

### Development

| Package | Purpose |
|---------|---------|
| `pyinstaller` | ≥6.11 | Windows executable packaging |
| `pytest` | ≥8.2 | Test runner |

### Python Version

**Requires Python 3.11 – 3.14.**

---

## License

MIT
