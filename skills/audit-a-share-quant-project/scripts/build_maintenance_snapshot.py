#!/usr/bin/env python3
"""Build a lightweight recurring maintenance snapshot for this repo."""

from __future__ import annotations

import argparse
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path

from find_audit_hotspots import CATEGORIES, collect_matches, iter_python_files


ARCHITECTURE_WARN_LINES = 800
ARCHITECTURE_HIGH_LINES = 1200
ARCHITECTURE_CRITICAL_LINES = 1800
PRODUCTION_DIRS = {"core", "scripts", "utils", "web", "config"}


def _git_lines(root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return [line.rstrip() for line in result.stdout.splitlines() if line.strip()]


def _count_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def _size_severity(line_count: int) -> str:
    if line_count >= ARCHITECTURE_CRITICAL_LINES:
        return "critical"
    if line_count >= ARCHITECTURE_HIGH_LINES:
        return "high"
    if line_count >= ARCHITECTURE_WARN_LINES:
        return "warn"
    return "ok"


def collect_architecture_size(root: Path) -> dict[str, object]:
    """Collect lightweight module-size risk indicators.

    This is intentionally a report, not a hard gate. Large files in execution
    and promotion paths often need staged refactors, so the snapshot should
    make the risk visible before anyone starts moving code around.
    """

    total_lines = 0
    file_counts = Counter()
    line_counts = Counter()
    largest_files: list[tuple[int, str]] = []
    large_production_files: list[dict[str, object]] = []

    for path in iter_python_files(root):
        rel_path = path.relative_to(root)
        top_dir = rel_path.parts[0] if rel_path.parts else "."
        line_count = _count_lines(path)

        total_lines += line_count
        file_counts[top_dir] += 1
        line_counts[top_dir] += line_count
        largest_files.append((line_count, str(rel_path)))

        if top_dir in PRODUCTION_DIRS and line_count >= ARCHITECTURE_WARN_LINES:
            large_production_files.append(
                {
                    "path": str(rel_path),
                    "lines": line_count,
                    "severity": _size_severity(line_count),
                }
            )

    largest_files.sort(reverse=True)
    large_production_files.sort(key=lambda item: int(item["lines"]), reverse=True)

    return {
        "total_python_lines": total_lines,
        "file_counts": dict(file_counts),
        "line_counts": dict(line_counts),
        "largest_files": largest_files[:10],
        "large_production_files": large_production_files,
    }


def _format_snapshot(root: Path) -> str:
    files_scanned, totals, _, by_file = collect_matches(root)
    architecture = collect_architecture_size(root)
    git_lines = _git_lines(root)
    lines: list[str] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines.append(f"# Maintenance Snapshot")
    lines.append("")
    lines.append(f"- generated_at: {now}")
    lines.append(f"- repo_root: {root}")
    lines.append(f"- python_files_scanned: {files_scanned}")
    lines.append("")
    lines.append("## Hotspot Counts")
    lines.append("")
    for category in CATEGORIES:
        lines.append(f"- {category}: {int(totals.get(category, 0))}")
    lines.append("")
    lines.append("## Top Hot Files")
    lines.append("")
    if by_file:
        for path, hits in by_file.most_common(10):
            lines.append(f"- {path}: {hits}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Architecture Size")
    lines.append("")
    lines.append(f"- total_python_lines: {int(architecture['total_python_lines'])}")
    large_prod = list(architecture["large_production_files"])
    lines.append(f"- large_production_files: {len(large_prod)}")
    lines.append(f"- warning_threshold_lines: {ARCHITECTURE_WARN_LINES}")
    lines.append(f"- high_threshold_lines: {ARCHITECTURE_HIGH_LINES}")
    lines.append(f"- critical_threshold_lines: {ARCHITECTURE_CRITICAL_LINES}")
    lines.append("")
    lines.append("### Python Files By Directory")
    lines.append("")
    file_counts = dict(architecture["file_counts"])
    line_counts = dict(architecture["line_counts"])
    for folder in sorted(file_counts):
        lines.append(f"- {folder}: files={file_counts[folder]}, lines={line_counts.get(folder, 0)}")
    lines.append("")
    lines.append("### Largest Python Files")
    lines.append("")
    largest_files = list(architecture["largest_files"])
    if largest_files:
        for line_count, path in largest_files:
            lines.append(f"- {path}: {line_count} lines")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("### Large Production Files")
    lines.append("")
    if large_prod:
        for item in large_prod[:15]:
            lines.append(f"- {item['severity']} {item['path']}: {item['lines']} lines")
        if len(large_prod) > 15:
            lines.append(f"- ... ({len(large_prod) - 15} more)")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Git Status")
    lines.append("")
    if git_lines:
        for line in git_lines[:50]:
            lines.append(f"- {line}")
        if len(git_lines) > 50:
            lines.append(f"- ... ({len(git_lines) - 50} more)")
    else:
        lines.append("- clean or unavailable")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build recurring maintenance snapshot")
    parser.add_argument("--root", type=str, default=None, help="Repo root. Defaults to the parent of the skill directory.")
    parser.add_argument("--out", type=str, default=None, help="Optional output file path.")
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[3]
    if not root.exists():
        raise SystemExit(f"Root not found: {root}")

    snapshot = _format_snapshot(root)
    if args.out:
        out = Path(args.out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(snapshot + "\n", encoding="utf-8")
        print(f"Wrote snapshot to {out}")
    else:
        print(snapshot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
