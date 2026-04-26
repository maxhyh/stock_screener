#!/usr/bin/env python3
"""Lightweight static hotspot scanner for this repo's audit workflow."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path


DEFAULT_DIRS = ("core", "scripts", "data", "utils", "web", "config", "tests")
CATEGORIES = {
    "lookahead": ("shift(-", "next_open", "exit_open", "open_to_open", "look-ahead", "future data", "future return"),
    "performance": ("iterrows(", "apply(", "transform(lambda", ".rolling(", "read_parquet("),
    "robustness": ("except Exception", "fillna(", ".ffill(", "retry", "fallback"),
    "execution": ("stamp", "slippage", "limit_up", "limit_down", "suspend", "blacklist"),
}


def iter_python_files(root: Path):
    for folder in DEFAULT_DIRS:
        base = root / folder
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path


def scan_file(path: Path, root: Path):
    rel = path.relative_to(root)
    matches: dict[str, list[str]] = defaultdict(list)
    text = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for lineno, line in enumerate(text, start=1):
        for category, needles in CATEGORIES.items():
            if any(needle in line for needle in needles):
                if category == "lookahead" and line.strip() == "from __future__ import annotations":
                    continue
                matches[category].append(f"{rel}:{lineno}: {line.strip()}")
    return matches


def collect_matches(root: Path):
    totals = Counter()
    by_category: dict[str, list[str]] = defaultdict(list)
    by_file = Counter()
    files_scanned = 0

    for path in iter_python_files(root):
        files_scanned += 1
        matches = scan_file(path, root)
        file_hits = 0
        for category, lines in matches.items():
            totals[category] += len(lines)
            by_category[category].extend(lines)
            file_hits += len(lines)
        if file_hits:
            by_file[str(path.relative_to(root))] += file_hits
    return files_scanned, totals, by_category, by_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Find likely audit hotspots in the repo")
    parser.add_argument("--root", type=str, default=None, help="Repo root. Defaults to the parent of the skill directory.")
    parser.add_argument("--limit", type=int, default=12, help="Max lines to print per category.")
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[3]
    if not root.exists():
        raise SystemExit(f"Root not found: {root}")

    files_scanned, totals, by_category, _ = collect_matches(root)
    print(f"Repo root: {root}")
    print(f"Python files scanned: {files_scanned}")
    print()
    for category in CATEGORIES:
        print(f"[{category}] matches={totals.get(category, 0)}")
        for line in by_category.get(category, [])[: max(1, int(args.limit))]:
            print(f"  {line}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
