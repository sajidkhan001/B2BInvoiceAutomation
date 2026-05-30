# B2B Document Automation

Local Windows-first Python automation for invoice and B2B packet processing. It runs as a PySide6 desktop and tray app, ingests Generic IMAP or Gmail attachments, scans and parses binaries in memory, validates extracted fields with Pydantic, routes low-confidence cases to human review, and appends verified structured records to Google Sheets.

The application is designed around a strict no-binary-retention rule. Original PDFs and images are never intentionally written to local disk, logs, Google Sheets, or cache. Only hashes, source metadata, structured fields, decisions, and audit events are retained.

## What Is Included

- Bounded in-memory ingestion envelopes with explicit wipe/release behavior.
- Magic-byte and extension allow-listing for PDF, JPEG, PNG, TIFF, and optional HEIC.
- ClamAV `clamd` stream scanning before parsing, with fail-closed defaults.
- Isolated parser execution using a process worker boundary.
- pdfplumber-based PDF extraction with multi-page table reconstruction heuristics.
- B2B document classification for invoices, credit notes, purchase orders, delivery notes/goods receipts, and receipts.
- Confidence scoring and routing at the default `0.90` threshold.
- Native desktop setup and review UI with close-to-tray background processing.
- Windows Credential Manager storage for IMAP passwords, Google OAuth tokens, and AI API keys.
- Gmail OAuth and Google Sheets OAuth helpers.
- OpenAI and Anthropic model listing with optional low-confidence extraction fallback.
- Google Sheets writer with append-only tabs, hidden idempotency index, audit rows, and formula-injection neutralization.
- Tests for privacy, routing, security rejection, table fallback, idempotency helpers, and memory limits.

## Quick Start

Create and install a virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -U pip
.\.venv\Scripts\python -m pip install -e .[dev]
```

Run tests:

```powershell
.\.venv\Scripts\python -m pytest
```

Start the desktop app:

```powershell
.\.venv\Scripts\b2bdoc-desktop
```

Build and install it like a normal Windows desktop app:

```powershell
.\scripts\build_desktop.ps1
.\scripts\install_desktop.ps1
```

If PowerShell blocks local scripts on your machine, run the same commands with a one-time execution-policy bypass:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_desktop.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_desktop.ps1
```

After installation, open **B2B Invoice Automation** from the Start menu or the desktop shortcut. The installed executable lives under:

```text
%LOCALAPPDATA%\Programs\B2B Invoice Automation\B2B Invoice Automation.exe
```

Uninstall for the current user:

```powershell
.\scripts\uninstall_desktop.ps1
```

Run one IMAP polling pass from the CLI:

```powershell
.\.venv\Scripts\b2bdoc imap-once
```

Check runtime configuration:

```powershell
.\.venv\Scripts\b2bdoc doctor
```

## Required Services

ClamAV is fail-closed by default. Install and run `clamd`, then set `B2B_CLAMAV_HOST` and `B2B_CLAMAV_PORT`. For local parser development only, set `B2B_ALLOW_UNSCANNED_DEV=true`; do not use that bypass for production data.

Google Sheets writing in the desktop app uses Google OAuth. In the Google Sheets tab, provide an OAuth client JSON, connect your Google account, and paste the target spreadsheet ID. The older CLI service-account path still supports:

- `B2B_GOOGLE_SHEET_ID`
- `B2B_GOOGLE_SERVICE_ACCOUNT_FILE`

The Google API client is constructed with discovery caching disabled to avoid local discovery-cache writes.

## Desktop Behavior

- Closing the main window hides it to the system tray when close-to-tray is enabled.
- The scheduler continues polling while the tray app is running.
- Use the tray menu or Dashboard Exit button to fully stop automation.
- Start with Windows registers the desktop app under the current user's Windows Run key.
- Non-secret preferences are stored under the user app-data folder; secrets are stored through keyring/Windows Credential Manager.

## Privacy Notes

This project avoids application-level binary persistence, but strict forensic zero-disk behavior also requires operating-system hardening: encrypted disk, restricted temp paths, disabled crash dumps where policy requires, careful pagefile policy, and a dedicated low-privilege Windows account.
