#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import zipfile


SUPPORTED_FILES = (
    "MEMORY.md",
    "SESSION-STATE.md",
    "working-buffer.md",
    "memory-capture.md",
)
SUPPORTED_DIRECTORIES = (
    "memory",
    "attachments",
)
ARCHIVE_VERSION = 1
SUBCOMMANDS = {"bootstrap", "session-start", "export", "import", "report", "doctor", "distill", "apply"}
DAILY_NOTE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
PLACEHOLDER_PREFIXES = (
    "这次有没有",
    "哪些事实会持续影响后续协作",
    "这次记忆属于哪个项目",
    "如果现在中断",
    "哪些内容只需要写进",
)


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def timestamp_slug(timestamp: str) -> str:
    return "".join(char for char in timestamp if char.isdigit())


def slug_fragment(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or fallback


def candidate_document_id(metadata: CaptureMetadata, generated_at: str) -> str:
    project = slug_fragment(metadata.project, "memory")
    session = slug_fragment(metadata.source_session, "session")
    return f"{project}__{session}__{timestamp_slug(generated_at)}"


def read_template(repo_root: Path, name: str) -> str:
    return (repo_root / "templates" / name).read_text(encoding="utf-8")


def ensure_file(path: Path, content: str) -> str:
    if path.exists():
        return "kept"
    path.write_text(content, encoding="utf-8")
    return "created"


def build_capture_content(
    repo_root: Path,
    generated_at: str,
    metadata: CaptureMetadata,
) -> str:
    template = read_template(repo_root, "memory-capture.md").rstrip() + "\n"
    scope_tags = ", ".join(metadata.scope_tags)
    return (
        "# memory-capture.md\n\n"
        f"> Generated at: {generated_at}\n\n"
        "## Capture metadata\n"
        f"- session_started_at: {metadata.session_started_at}\n"
        f"- project: {metadata.project}\n"
        f"- scope_tags: {scope_tags}\n"
        f"- source_session: {metadata.source_session}\n"
        f"- candidate_document_id: {candidate_document_id(metadata, generated_at)}\n"
        "- stability: review\n\n"
        f"{template}"
    )


def write_capture_file(
    workspace: Path,
    generated_at: str,
    repo_root: Path,
    metadata: CaptureMetadata,
    *,
    refresh: bool,
) -> str:
    capture_path = workspace / "memory-capture.md"
    if capture_path.exists() and not refresh:
        return "kept"
    existed = capture_path.exists()
    capture_path.write_text(
        build_capture_content(repo_root, generated_at, metadata),
        encoding="utf-8",
    )
    if refresh and existed:
        return "refreshed"
    return "created"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap, export, and import lightweight memory workspace files."
    )
    subparsers = parser.add_subparsers(dest="command")

    bootstrap = subparsers.add_parser(
        "bootstrap",
        help="Create baseline memory capture files in a workspace.",
    )
    add_workspace_arguments(bootstrap)
    bootstrap.add_argument(
        "--refresh-capture",
        action="store_true",
        help="Overwrite memory-capture.md with a regenerated capture sheet.",
    )
    add_capture_metadata_arguments(bootstrap)

    session_start = subparsers.add_parser(
        "session-start",
        help="Ensure recovery files exist at the beginning of a session.",
    )
    add_workspace_arguments(session_start)
    session_start.add_argument(
        "--refresh-capture",
        action="store_true",
        help="Overwrite memory-capture.md with a regenerated capture sheet.",
    )
    add_capture_metadata_arguments(session_start)

    export_parser = subparsers.add_parser(
        "export",
        help="Export memory workspace files into a portable zip archive.",
    )
    add_workspace_arguments(export_parser)
    export_parser.add_argument(
        "--output",
        required=True,
        help="Output zip file path or output directory for the archive.",
    )

    import_parser = subparsers.add_parser(
        "import",
        help="Import a memory workspace archive into a target workspace.",
    )
    add_workspace_arguments(import_parser)
    import_parser.add_argument(
        "--input",
        required=True,
        help="Input zip archive path.",
    )
    import_parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove supported memory files and directories before restoring the archive.",
    )
    report_parser = subparsers.add_parser(
        "report",
        help="Summarize the workspace state and optionally emit a maintenance report.",
    )
    add_workspace_arguments(report_parser, include_generated_at=False)
    report_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the report payload as JSON to stdout.",
    )
    report_parser.add_argument(
        "--output",
        help="Optional Markdown file path for the report.",
    )
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run scoped health checks for the active local memory layers.",
    )
    add_workspace_arguments(doctor_parser, include_generated_at=False)
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the doctor payload as JSON to stdout.",
    )
    doctor_parser.add_argument(
        "--output",
        help="Optional Markdown file path for the doctor report.",
    )
    doctor_parser.add_argument(
        "--obsidian-vault",
        help="Optional Obsidian vault path to check when Obsidian is actively in use.",
    )
    distill_parser = subparsers.add_parser(
        "distill",
        help="Summarize candidate memory into review-ready buckets without editing MEMORY.md.",
    )
    add_workspace_arguments(distill_parser, include_generated_at=False)
    distill_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the distill payload as JSON to stdout.",
    )
    distill_parser.add_argument(
        "--output",
        help="Optional Markdown file path for the distill summary.",
    )
    apply_parser = subparsers.add_parser(
        "apply",
        help="Write distilled candidate memory into MEMORY.md using idempotent document ids.",
    )
    add_workspace_arguments(apply_parser, include_generated_at=False)
    return parser


def add_workspace_arguments(parser: argparse.ArgumentParser, include_generated_at: bool = True) -> None:
    parser.add_argument(
        "--workspace",
        required=True,
        help="Target workspace directory where memory files should be created or restored.",
    )
    if include_generated_at:
        parser.add_argument(
            "--generated-at",
            help="Optional timestamp used in generated files and archive metadata.",
        )


def add_capture_metadata_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--session-id",
        help="Optional session identifier used to scope the current capture sheet.",
    )
    parser.add_argument(
        "--project",
        help="Optional project or repository name for the current capture sheet.",
    )
    parser.add_argument(
        "--scope-tag",
        action="append",
        default=[],
        help="Repeatable scope tag used to label the current capture sheet.",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in SUBCOMMANDS:
        argv = ["bootstrap", *argv]
    return build_parser().parse_args(argv)


def collect_workspace_paths(workspace: Path) -> list[Path]:
    paths: list[Path] = []
    for name in SUPPORTED_FILES:
        candidate = workspace / name
        if candidate.is_file():
            paths.append(candidate)
    for directory_name in SUPPORTED_DIRECTORIES:
        directory = workspace / directory_name
        if directory.is_dir():
            for path in sorted(item for item in directory.rglob("*") if item.is_file()):
                paths.append(path)
    return paths


@dataclass
class ReportData:
    workspace: Path
    supported_files: dict[str, bool]
    memory_note_count: int
    attachments_count: int
    latest_daily_note: Path | None
    warnings: list[str]


@dataclass
class CaptureMetadata:
    session_started_at: str
    project: str
    scope_tags: list[str]
    source_session: str


@dataclass
class DoctorCheck:
    status: str
    warnings: list[str]


@dataclass
class DistillData:
    metadata: dict[str, object]
    suggested_memory: list[dict[str, str]]
    recovery_only: list[str]
    follow_up: list[str]


MEMORY_FILE_HEADER = (
    "# MEMORY.md\n\n"
    "> Long-term memory. Distill stable facts, preferences, and decisions here.\n\n"
    "## Distilled Memory Entries\n"
)


def collect_report_data(workspace: Path) -> ReportData:
    supported_files = {
        name: (workspace / name).is_file() for name in SUPPORTED_FILES
    }
    memory_dir = workspace / "memory"
    memory_notes: list[Path] = []
    if memory_dir.is_dir():
        memory_notes = sorted(
            item
            for item in memory_dir.rglob("*.md")
            if item.is_file() and DAILY_NOTE_PATTERN.fullmatch(item.name)
        )
    attachments_dir = workspace / "attachments"
    attachments_count = 0
    if attachments_dir.is_dir():
        attachments_count = sum(
            1 for item in attachments_dir.rglob("*") if item.is_file()
        )
    warnings: list[str] = []
    for name, exists in supported_files.items():
        if not exists:
            warnings.append(f"Missing supported file: {name}")
    if not memory_dir.is_dir():
        warnings.append("memory directory is missing")
    elif not memory_notes:
        warnings.append("memory directory has no daily notes")
    if not attachments_dir.is_dir():
        warnings.append("attachments directory is missing")
    elif attachments_count == 0:
        warnings.append("attachments directory is empty")
    latest_daily_note = memory_notes[-1] if memory_notes else None
    return ReportData(
        workspace=workspace,
        supported_files=supported_files,
        memory_note_count=len(memory_notes),
        attachments_count=attachments_count,
        latest_daily_note=latest_daily_note,
        warnings=warnings,
    )


def capture_metadata_from_args(args: argparse.Namespace, generated_at: str) -> CaptureMetadata:
    return CaptureMetadata(
        session_started_at=generated_at,
        project=getattr(args, "project", "") or "",
        scope_tags=list(getattr(args, "scope_tag", []) or []),
        source_session=getattr(args, "session_id", "") or "",
    )


def format_report_text(data: ReportData) -> str:
    lines: list[str] = [
        f"Memory workspace report for {data.workspace}",
        "",
        "Supported files:",
    ]
    for name in SUPPORTED_FILES:
        status = "present" if data.supported_files.get(name) else "missing"
        lines.append(f"  {name}: {status}")
    lines.extend(
        [
            "",
            "Directories:",
            f"  memory: {data.memory_note_count} daily note(s)",
            f"  attachments: {data.attachments_count} attachment(s)",
            "",
        ]
    )
    latest_note = (
        data.latest_daily_note.relative_to(data.workspace).as_posix()
        if data.latest_daily_note
        else "none"
    )
    lines.append(f"Latest daily note: {latest_note}")
    lines.append("")
    if data.warnings:
        lines.append("Warnings:")
        lines.extend(f"  - {warning}" for warning in data.warnings)
    else:
        lines.append("Warnings: none")
    return "\n".join(lines)


def format_report_markdown(data: ReportData) -> str:
    latest_note = (
        data.latest_daily_note.relative_to(data.workspace).as_posix()
        if data.latest_daily_note
        else "none"
    )
    lines: list[str] = [
        "# Memory workspace report",
        "",
        f"- Workspace: {data.workspace}",
        "",
        "## Supported files",
    ]
    for name in SUPPORTED_FILES:
        status = "present" if data.supported_files.get(name) else "missing"
        lines.append(f"- `{name}`: {status}")
    lines.extend(
        [
            "",
            "## Directories",
            f"- `memory`: {data.memory_note_count} daily note(s)",
            f"- `attachments`: {data.attachments_count} attachment(s)",
            "",
            "## Latest daily note",
            f"- {latest_note}",
            "",
            "## Warnings",
        ]
    )
    if data.warnings:
        lines.extend(f"- {warning}" for warning in data.warnings)
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def report_payload(data: ReportData) -> dict[str, object]:
    return {
        "workspace": str(data.workspace),
        "supported_files": data.supported_files,
        "memory_note_count": data.memory_note_count,
        "attachments_count": data.attachments_count,
        "latest_daily_note": (
            data.latest_daily_note.relative_to(data.workspace).as_posix()
            if data.latest_daily_note
            else None
        ),
        "warnings": data.warnings,
    }


def parse_capture_sections(capture_text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    for raw_line in capture_text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            current_section = line[3:].strip()
            sections.setdefault(current_section, [])
            continue
        if not current_section:
            continue
        if line.startswith("- "):
            sections[current_section].append(line[2:].strip())
    return sections


def is_placeholder_item(item: str) -> bool:
    normalized = item.strip()
    if not normalized:
        return True
    if normalized.startswith("`volatile`、`review`、`stable`"):
        return True
    return normalized.startswith(PLACEHOLDER_PREFIXES)


def split_scope_tags(raw_tags: str) -> list[str]:
    if not raw_tags:
        return []
    return [part.strip() for part in raw_tags.split(",") if part.strip()]


def collect_distill_data(workspace: Path) -> DistillData:
    capture_path = workspace / "memory-capture.md"
    if not capture_path.is_file():
        raise FileNotFoundError(f"memory-capture.md does not exist: {capture_path}")
    sections = parse_capture_sections(capture_path.read_text(encoding="utf-8"))

    metadata_pairs: dict[str, str] = {}
    for item in sections.get("Capture metadata", []):
        if ":" not in item:
            continue
        key, value = item.split(":", 1)
        metadata_pairs[key.strip()] = value.strip()

    scope_tags = split_scope_tags(metadata_pairs.get("scope_tags", ""))
    for extra_tag in sections.get("候选标签", []):
        if not is_placeholder_item(extra_tag):
            scope_tags.append(extra_tag)

    deduped_tags: list[str] = []
    for tag in scope_tags:
        if tag not in deduped_tags:
            deduped_tags.append(tag)

    stability = metadata_pairs.get("stability", "")
    for item in sections.get("候选稳定性", []):
        if not is_placeholder_item(item):
            stability = item

    suggested_memory: list[dict[str, str]] = []
    seen_suggestions: set[tuple[str, str]] = set()
    for bucket in ("候选决策", "候选踩坑", "候选长期记忆"):
        for item in sections.get(bucket, []):
            if is_placeholder_item(item):
                continue
            signature = (bucket, item)
            if signature in seen_suggestions:
                continue
            seen_suggestions.add(signature)
            suggested_memory.append(
                {
                    "bucket": bucket,
                    "text": item,
                    "project": metadata_pairs.get("project", ""),
                    "source_session": metadata_pairs.get("source_session", ""),
                    "stability": stability,
                }
            )

    recovery_only = [
        item for item in sections.get("只留在当前恢复层", [])
        if not is_placeholder_item(item)
    ]
    follow_up = [
        item for item in sections.get("明日续接", [])
        if not is_placeholder_item(item)
    ]

    return DistillData(
        metadata={
            "project": metadata_pairs.get("project", ""),
            "source_session": metadata_pairs.get("source_session", ""),
            "session_started_at": metadata_pairs.get("session_started_at", ""),
            "candidate_document_id": metadata_pairs.get("candidate_document_id", ""),
            "scope_tags": deduped_tags,
            "stability": stability,
        },
        suggested_memory=suggested_memory,
        recovery_only=recovery_only,
        follow_up=follow_up,
    )


def relative_archive_name(path: Path, workspace: Path) -> str:
    return path.relative_to(workspace).as_posix()


def manifest_payload(
    *,
    generated_at: str,
    workspace: Path,
    included_paths: list[str],
    archive_kind: str,
) -> dict[str, object]:
    return {
        "archive_version": ARCHIVE_VERSION,
        "archive_kind": archive_kind,
        "generated_at": generated_at,
        "source_workspace": str(workspace),
        "included_paths": included_paths,
    }


def create_archive(
    *,
    workspace: Path,
    archive_path: Path,
    entries: list[Path],
    generated_at: str,
    archive_kind: str,
) -> Path:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    included_paths = [relative_archive_name(path, workspace) for path in entries]
    payload = manifest_payload(
        generated_at=generated_at,
        workspace=workspace,
        included_paths=included_paths,
        archive_kind=archive_kind,
    )
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(payload, ensure_ascii=False, indent=2))
        for entry, archive_name in zip(entries, included_paths):
            archive.write(entry, archive_name)
    return archive_path


def resolve_output_archive(output: str, generated_at: str) -> Path:
    output_path = Path(output).expanduser().resolve()
    if output_path.suffix.lower() == ".zip":
        return output_path
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path / f"memory-backup-{timestamp_slug(generated_at)}.zip"


def safe_members_from_manifest(archive: zipfile.ZipFile) -> list[str]:
    try:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    except KeyError as error:
        raise ValueError("Archive is missing manifest.json.") from error

    included_paths = manifest.get("included_paths")
    if not isinstance(included_paths, list) or not all(isinstance(item, str) for item in included_paths):
        raise ValueError("Archive manifest has invalid included_paths.")

    archive_names = set(archive.namelist())
    safe_paths: list[str] = []
    for item in included_paths:
        pure_path = PurePosixPath(item)
        if pure_path.is_absolute() or ".." in pure_path.parts:
            raise ValueError(f"Archive contains unsafe path: {item}")
        if item not in archive_names:
            raise ValueError(f"Archive is missing expected file: {item}")
        safe_paths.append(item)
    return safe_paths


def create_bootstrap_files(
    workspace: Path,
    generated_at: str,
    repo_root: Path,
    *,
    metadata: CaptureMetadata,
    refresh_capture: bool,
) -> None:
    session_status = ensure_file(
        workspace / "SESSION-STATE.md",
        read_template(repo_root, "SESSION-STATE.md"),
    )
    buffer_status = ensure_file(
        workspace / "working-buffer.md",
        read_template(repo_root, "working-buffer.md"),
    )

    capture_status = write_capture_file(
        workspace,
        generated_at,
        repo_root,
        metadata,
        refresh=refresh_capture,
    )

    print(f"SESSION-STATE.md: {session_status}")
    print(f"working-buffer.md: {buffer_status}")
    print(f"memory-capture.md: {capture_status}")


def handle_bootstrap(args: argparse.Namespace, repo_root: Path) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    generated_at = args.generated_at or iso_now()
    create_bootstrap_files(
        workspace,
        generated_at,
        repo_root,
        metadata=capture_metadata_from_args(args, generated_at),
        refresh_capture=args.refresh_capture,
    )
    return 0


def handle_session_start(args: argparse.Namespace, repo_root: Path) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    generated_at = args.generated_at or iso_now()
    create_bootstrap_files(
        workspace,
        generated_at,
        repo_root,
        metadata=capture_metadata_from_args(args, generated_at),
        refresh_capture=args.refresh_capture,
    )
    print("Session start: ready")
    return 0


def handle_export(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        print(f"Workspace does not exist: {workspace}", file=sys.stderr)
        return 1

    generated_at = args.generated_at or iso_now()
    entries = collect_workspace_paths(workspace)
    if not entries:
        print("No supported memory files were found to export.", file=sys.stderr)
        return 1

    archive_path = resolve_output_archive(args.output, generated_at)
    create_archive(
        workspace=workspace,
        archive_path=archive_path,
        entries=entries,
        generated_at=generated_at,
        archive_kind="export",
    )
    print(f"Exported backup: {archive_path}")
    return 0


def backup_existing_workspace_state(workspace: Path, generated_at: str) -> Path | None:
    existing_entries = collect_workspace_paths(workspace)
    if not existing_entries:
        return None
    archive_path = workspace / f"memory-import-backup-{timestamp_slug(generated_at)}.zip"
    create_archive(
        workspace=workspace,
        archive_path=archive_path,
        entries=existing_entries,
        generated_at=generated_at,
        archive_kind="pre-import-backup",
    )
    return archive_path


def clear_supported_workspace_state(workspace: Path) -> None:
    for name in SUPPORTED_FILES:
        candidate = workspace / name
        if candidate.exists():
            candidate.unlink()
    for directory_name in SUPPORTED_DIRECTORIES:
        directory = workspace / directory_name
        if directory.exists():
            shutil.rmtree(directory)


def restore_archive(archive: zipfile.ZipFile, workspace: Path, members: list[str]) -> None:
    for member in members:
        target_path = workspace / PurePosixPath(member)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(archive.read(member))


def handle_import(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    archive_path = Path(args.input).expanduser().resolve()
    if not archive_path.is_file():
        print(f"Archive does not exist: {archive_path}", file=sys.stderr)
        return 1

    generated_at = args.generated_at or iso_now()
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = safe_members_from_manifest(archive)
            backup_path = backup_existing_workspace_state(workspace, generated_at)
            if args.clean:
                clear_supported_workspace_state(workspace)
            restore_archive(archive, workspace, members)
    except (ValueError, zipfile.BadZipFile) as error:
        print(f"Import failed: {error}", file=sys.stderr)
        return 1

    mode = "clean" if args.clean else "conservative"
    print(f"Import mode: {mode}")
    if backup_path is None:
        print("Pre-import backup: none needed")
    else:
        print(f"Pre-import backup: {backup_path}")
    print(f"Imported backup: {archive_path}")
    return 0


def handle_report(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        print(f"Workspace does not exist: {workspace}", file=sys.stderr)
        return 1
    report_data = collect_report_data(workspace)
    if args.json:
        print(json.dumps(report_payload(report_data), ensure_ascii=False, indent=2))
    else:
        print(format_report_text(report_data))
    output_path = getattr(args, "output", None)
    if output_path:
        destination = Path(output_path).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(format_report_markdown(report_data), encoding="utf-8")
        if not args.json:
            print(f"Report written: {destination}")
    return 0


def doctor_checks(workspace: Path, obsidian_vault: str | None) -> dict[str, DoctorCheck]:
    report_data = collect_report_data(workspace)
    checks = {
        "local_recovery": DoctorCheck(
            status="ok" if not report_data.warnings else "warn",
            warnings=report_data.warnings,
        )
    }
    if obsidian_vault:
        vault_path = Path(obsidian_vault).expanduser().resolve()
        warnings: list[str] = []
        if not vault_path.exists():
            warnings.append(f"Obsidian vault does not exist: {vault_path}")
        elif not vault_path.is_dir():
            warnings.append(f"Obsidian vault is not a directory: {vault_path}")
        checks["obsidian"] = DoctorCheck(
            status="ok" if not warnings else "warn",
            warnings=warnings,
        )
    return checks


def doctor_payload(workspace: Path, checks: dict[str, DoctorCheck]) -> dict[str, object]:
    return {
        "workspace": str(workspace),
        "checks": {
            name: {
                "status": check.status,
                "warnings": check.warnings,
            }
            for name, check in checks.items()
        },
    }


def format_doctor_text(workspace: Path, checks: dict[str, DoctorCheck]) -> str:
    lines: list[str] = [f"Memory workspace doctor for {workspace}", ""]
    for name, check in checks.items():
        lines.append(f"{name}: {check.status}")
        if check.warnings:
            lines.extend(f"  - {warning}" for warning in check.warnings)
        else:
            lines.append("  - none")
        lines.append("")
    return "\n".join(lines).rstrip()


def format_doctor_markdown(workspace: Path, checks: dict[str, DoctorCheck]) -> str:
    lines: list[str] = [
        "# Memory workspace doctor",
        "",
        f"- Workspace: {workspace}",
        "",
    ]
    for name, check in checks.items():
        lines.append(f"## {name}")
        lines.append(f"- status: {check.status}")
        lines.append("- warnings:")
        if check.warnings:
            lines.extend(f"  - {warning}" for warning in check.warnings)
        else:
            lines.append("  - none")
        lines.append("")
    return "\n".join(lines)


def handle_doctor(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        print(f"Workspace does not exist: {workspace}", file=sys.stderr)
        return 1
    checks = doctor_checks(workspace, args.obsidian_vault)
    if args.json:
        print(json.dumps(doctor_payload(workspace, checks), ensure_ascii=False, indent=2))
    else:
        print(format_doctor_text(workspace, checks))
    if args.output:
        destination = Path(args.output).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(format_doctor_markdown(workspace, checks), encoding="utf-8")
        if not args.json:
            print(f"Doctor report written: {destination}")
    return 0


def distill_payload(workspace: Path, data: DistillData) -> dict[str, object]:
    return {
        "workspace": str(workspace),
        "metadata": data.metadata,
        "suggested_memory": data.suggested_memory,
        "recovery_only": data.recovery_only,
        "follow_up": data.follow_up,
    }


def format_distill_text(data: DistillData) -> str:
    lines = ["Memory capture distill", ""]
    lines.append(f"Project: {data.metadata.get('project', '') or 'none'}")
    lines.append(f"Session: {data.metadata.get('source_session', '') or 'none'}")
    lines.append(
        "Scope tags: "
        + (", ".join(data.metadata.get("scope_tags", [])) or "none")
    )
    lines.append(f"Stability: {data.metadata.get('stability', '') or 'review'}")
    lines.append("")
    lines.append("Suggested memory:")
    if data.suggested_memory:
        for item in data.suggested_memory:
            lines.append(f"  - [{item['bucket']}] {item['text']}")
    else:
        lines.append("  - none")
    lines.append("")
    lines.append("Recovery only:")
    if data.recovery_only:
        lines.extend(f"  - {item}" for item in data.recovery_only)
    else:
        lines.append("  - none")
    lines.append("")
    lines.append("Follow up:")
    if data.follow_up:
        lines.extend(f"  - {item}" for item in data.follow_up)
    else:
        lines.append("  - none")
    return "\n".join(lines)


def format_distill_markdown(workspace: Path, data: DistillData) -> str:
    lines = [
        "# Memory capture distill",
        "",
        f"- Workspace: {workspace}",
        f"- Project: {data.metadata.get('project', '') or 'none'}",
        f"- Session: {data.metadata.get('source_session', '') or 'none'}",
        f"- Document ID: `{data.metadata.get('candidate_document_id', '') or 'none'}`",
        f"- Stability: {data.metadata.get('stability', '') or 'review'}",
        "",
        "## Scope tags",
    ]
    tags = data.metadata.get("scope_tags", [])
    if tags:
        lines.extend(f"- {tag}" for tag in tags)
    else:
        lines.append("- none")
    lines.extend(["", "## Suggested memory"])
    bucket_order = ("候选决策", "候选踩坑", "候选长期记忆")
    if data.suggested_memory:
        by_bucket = {
            bucket: [item["text"] for item in data.suggested_memory if item["bucket"] == bucket]
            for bucket in bucket_order
        }
        for bucket in bucket_order:
            if not by_bucket[bucket]:
                continue
            lines.append(f"### {bucket}")
            lines.extend(f"- {text}" for text in by_bucket[bucket])
    else:
        lines.append("- none")
    lines.extend(["", "## Recovery only"])
    if data.recovery_only:
        lines.extend(f"- {item}" for item in data.recovery_only)
    else:
        lines.append("- none")
    lines.extend(["", "## Follow up"])
    if data.follow_up:
        lines.extend(f"- {item}" for item in data.follow_up)
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def ensure_memory_file(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return MEMORY_FILE_HEADER


def memory_entry_markdown(data: DistillData) -> str:
    document_id = data.metadata.get("candidate_document_id", "") or "none"
    project = data.metadata.get("project", "") or "none"
    session = data.metadata.get("source_session", "") or "none"
    stability = data.metadata.get("stability", "") or "review"
    tags = data.metadata.get("scope_tags", [])
    lines = [
        f"### Entry `{document_id}`",
        f"- Project: {project}",
        f"- Session: {session}",
        f"- Stability: {stability}",
        "- Scope tags: " + (", ".join(tags) if tags else "none"),
        "",
    ]
    bucket_order = ("候选决策", "候选踩坑", "候选长期记忆")
    by_bucket = {
        bucket: [item["text"] for item in data.suggested_memory if item["bucket"] == bucket]
        for bucket in bucket_order
    }
    for bucket in bucket_order:
        if not by_bucket[bucket]:
            continue
        lines.append(f"### {bucket}")
        lines.extend(f"- {text}" for text in by_bucket[bucket])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def handle_apply(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        print(f"Workspace does not exist: {workspace}", file=sys.stderr)
        return 1
    try:
        data = collect_distill_data(workspace)
    except FileNotFoundError as error:
        print(str(error), file=sys.stderr)
        return 1

    document_id = data.metadata.get("candidate_document_id", "") or ""
    if not document_id:
        print("Distill data is missing candidate_document_id.", file=sys.stderr)
        return 1
    if not data.suggested_memory:
        print("Applied distilled memory: 0 entries added, 0 skipped")
        return 0

    memory_path = workspace / "MEMORY.md"
    memory_text = ensure_memory_file(memory_path)
    if document_id in memory_text:
        print("Applied distilled memory: 0 entries added, 1 skipped")
        return 0

    if not memory_text.endswith("\n"):
        memory_text += "\n"
    if "## Distilled Memory Entries" not in memory_text:
        memory_text += "\n## Distilled Memory Entries\n"
    if not memory_text.endswith("\n\n"):
        memory_text += "\n"
    memory_text += memory_entry_markdown(data)
    memory_path.write_text(memory_text, encoding="utf-8")
    print("Applied distilled memory: 1 entry added, 0 skipped")
    return 0


def handle_distill(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        print(f"Workspace does not exist: {workspace}", file=sys.stderr)
        return 1
    try:
        data = collect_distill_data(workspace)
    except FileNotFoundError as error:
        print(str(error), file=sys.stderr)
        return 1
    payload = distill_payload(workspace, data)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_distill_text(data))
    if args.output:
        destination = Path(args.output).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(format_distill_markdown(workspace, data), encoding="utf-8")
        if not args.json:
            print(f"Distill report written: {destination}")
    return 0


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    if args.command == "bootstrap":
        return handle_bootstrap(args, repo_root)
    if args.command == "session-start":
        return handle_session_start(args, repo_root)
    if args.command == "export":
        return handle_export(args)
    if args.command == "import":
        return handle_import(args)
    if args.command == "report":
        return handle_report(args)
    if args.command == "doctor":
        return handle_doctor(args)
    if args.command == "distill":
        return handle_distill(args)
    if args.command == "apply":
        return handle_apply(args)
    print(f"Unsupported command: {args.command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
