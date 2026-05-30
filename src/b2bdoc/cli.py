from __future__ import annotations

import argparse
import shutil
import sys

from .config import Settings
from .imap_ingest import IMAPIngestor
from .memory import BoundedMemoryManager
from .pipeline import DocumentPipeline
from .sheets import GoogleSheetsLedger, NullLedgerWriter


def _build_pipeline(settings: Settings) -> tuple[BoundedMemoryManager, DocumentPipeline]:
    memory = BoundedMemoryManager(settings.max_file_bytes, settings.max_inflight_bytes)
    ledger = GoogleSheetsLedger.from_settings(settings) or NullLedgerWriter()
    pipeline = DocumentPipeline(settings=settings, ledger_writer=ledger)
    return memory, pipeline


def doctor(settings: Settings) -> int:
    print("B2B document automation doctor")
    print(f"max_file_mb={settings.max_file_mb}")
    print(f"max_pages={settings.max_pages}")
    print(f"max_inflight_mb={settings.max_inflight_mb}")
    print(f"confidence_threshold={settings.confidence_threshold}")
    print(f"parser_workers={settings.parser_workers}")
    print(f"clamav_host={settings.clamav_host}")
    print(f"clamav_port={settings.clamav_port}")
    print(f"allow_unscanned_dev={settings.allow_unscanned_dev}")
    print(f"clamdscan_on_path={bool(shutil.which('clamdscan'))}")
    print(f"imap_configured={bool(settings.imap_host and settings.imap_user and settings.imap_password)}")
    print(f"google_sheets_configured={bool(settings.google_sheet_id and settings.google_service_account_file)}")
    return 0


def imap_once(settings: Settings) -> int:
    memory, pipeline = _build_pipeline(settings)
    results = IMAPIngestor(settings, memory, pipeline).run_once()
    for result in results:
        print(f"{result.status.value}: {result.reason or (result.parsed_document.document_number if result.parsed_document else '')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="b2bdoc")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor")
    subparsers.add_parser("imap-once")
    subparsers.add_parser("desktop")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.command == "doctor":
        return doctor(settings)
    if args.command == "imap-once":
        return imap_once(settings)
    if args.command == "desktop":
        from .desktop.main import main as desktop_main

        return desktop_main()
    return 2


if __name__ == "__main__":
    sys.exit(main())
