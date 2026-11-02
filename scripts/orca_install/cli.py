"""Command-line interface for ``manage_installation.py``."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence
import argparse
import sys

from .errors import InstallationError
from .installer import InstallResult, install
from .status import collect_status
from .uninstaller import UninstallResult, uninstall


def _default_bundle_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _print_list(prefix: str, items: Sequence[str], limit: int = 10) -> None:
    if not items:
        return
    print(f"{prefix}: {len(items)}")
    for item in items[:limit]:
        print(f"  {item}")
    if len(items) > limit:
        print(f"  ... and {len(items) - limit} more")


def _print_install(result: InstallResult) -> None:
    if result.outcome == "dry-run":
        print("Dry run: install")
        for note in result.notes:
            print(note)
        if result.updated or result.added:
            print(f"Files: {result.updated + result.added} ({result.updated} updated, {result.added} added)")
        _print_list("Local edits preserved", result.preserved_edits)
        print("No files were changed.")
        return
    if result.outcome == "already-installed":
        print(f"Installation: already installed ({result.installation_id})")
        print(f"Backup: {result.backup_path}")
        for note in result.notes:
            print(note)
        _print_list("Modified since install", result.modified_since_install)
        _print_list("Missing since install", result.missing_since_install)
        _print_list("Unexpected paths", result.unexpected_paths)
        return
    print("Installation: installed")
    print(f"Installation ID: {result.installation_id}")
    print(f"Backup: {result.backup_path}")
    print(f"Files: {result.updated + result.added} ({result.updated} updated, {result.added} added)")
    _print_list("Local edits preserved", result.preserved_edits)
    for note in result.notes:
        print(note)


def _print_uninstall(result: UninstallResult) -> None:
    if result.outcome == "dry-run":
        print("Dry run: uninstall")
        for note in result.notes:
            print(note)
        print(
            f"Files: {result.restored} would be restored, {result.removed} removed, "
            f"{result.archived} archived"
        )
        print("No files were changed.")
        return
    if result.outcome == "not-installed":
        print("Installation: not installed")
        print(f"Backup: {result.backup_path or 'none'}")
        for note in result.notes:
            print(note)
        return
    if result.outcome == "recovered-install":
        print("Installation: uninstalled")
        print(f"Backup retained: {result.backup_path}")
        for note in result.notes:
            print(note)
        return
    print("Installation: uninstalled")
    print(f"Installation ID: {result.installation_id}")
    print(f"Files: {result.restored} restored, {result.removed} removed")
    print(f"Recovery archive: {result.recovery_archive or 'none needed'}")
    print(f"Backup retained: {result.backup_path}")
    if result.retained_directories:
        _print_list("Kept non-empty directories", result.retained_directories)
    for note in result.notes:
        print(note)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manage_installation.py",
        description=(
            "Install, inspect, or uninstall the Orca advanced orchestration bundle "
            "in a supported Orca source checkout."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser(
        "install", help="verify the bundle, back up, and patch a source checkout"
    )
    install_parser.add_argument(
        "--source", required=True, help="path to the Orca source checkout (its Git root)"
    )
    install_parser.add_argument(
        "--dry-run", action="store_true", help="show planned actions without changing anything"
    )

    status_parser = subparsers.add_parser(
        "status", help="read-only installation status for a source checkout"
    )
    status_parser.add_argument(
        "--source", required=True, help="path to the Orca source checkout (its Git root)"
    )

    uninstall_parser = subparsers.add_parser(
        "uninstall",
        help="archive post-install edits, then restore the pre-install backup",
    )
    uninstall_parser.add_argument(
        "--source", required=True, help="path to the Orca source checkout (its Git root)"
    )
    uninstall_parser.add_argument(
        "--dry-run", action="store_true", help="show planned actions without changing anything"
    )
    return parser


def main(
    argv: Optional[Sequence[str]] = None,
    bundle_root: Optional[Path | str] = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    bundle = Path(bundle_root) if bundle_root is not None else _default_bundle_root()
    try:
        if args.command == "install":
            result = install(bundle, args.source, dry_run=args.dry_run)
            _print_install(result)
            return 0
        if args.command == "status":
            report = collect_status(args.source)
            print(report.render())
            return 0
        if args.command == "uninstall":
            result = uninstall(args.source, dry_run=args.dry_run)
            _print_uninstall(result)
            return 0
        parser.error(f"unknown command: {args.command}")
    except InstallationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: filesystem operation failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 1
    return 2
