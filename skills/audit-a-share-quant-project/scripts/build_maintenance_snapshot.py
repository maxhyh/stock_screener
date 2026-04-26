#!/usr/bin/env python3
"""Build a lightweight recurring maintenance snapshot for this repo."""

from __future__ import annotations

import argparse
import subprocess
from datetime import datetime
from pathlib import Path

from find_audit_hotspots import CATEGORIES, collect_matches


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


def _format_snapshot(root: Path) -> str:
    files_scanned, totals, _, by_file = collect_matches(root)
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
