#!/usr/bin/env python3
"""Deterministic project memory evolution.

The memory system is intentionally simple and auditable:

- long-term facts live in memory/learnings.md and memory/errors.md
- reusable entries are promoted into memory/actives.md
- a nightly review draft is generated for human/agent inspection

No LLM call is required. This script extracts structured markdown entries and
keeps the active boot context small enough to read at the start of each session.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
MEMORY_DIR = BASE_DIR / "memory"

AUTO_START = "<!-- memory:auto:start -->"
AUTO_END = "<!-- memory:auto:end -->"


TRUE_VALUES = {"1", "true", "yes", "y", "on", "是", "可", "需要", "active"}
FALSE_VALUES = {"0", "false", "no", "n", "off", "否", "不", "resolved", "archive", "archived"}


@dataclass(frozen=True)
class MemoryEntry:
    source: str
    heading: str
    body: str
    meta: dict[str, str]
    hash_id: str

    @property
    def title(self) -> str:
        title = re.sub(r"^\d{4}-\d{2}-\d{2}\s*\|\s*", "", self.heading).strip()
        return title or self.heading.strip()

    @property
    def tags(self) -> list[str]:
        return _parse_tags(self.meta.get("tags", ""))

    @property
    def confidence(self) -> str:
        return self.meta.get("confidence", "").strip() or "unspecified"

    @property
    def evidence(self) -> str:
        return self.meta.get("evidence", "").strip()

    @property
    def action(self) -> str:
        return (
            self.meta.get("action", "").strip()
            or self.meta.get("mitigation", "").strip()
            or self._first_non_meta_sentence()
        )

    def _first_non_meta_sentence(self) -> str:
        lines = []
        for raw in self.body.splitlines():
            line = raw.strip()
            if not line or _parse_meta_line(line):
                continue
            lines.append(line)
        text = " ".join(lines).strip()
        if not text:
            return ""
        parts = re.split(r"(?<=[。.!?])\s+", text)
        return parts[0][:220].strip()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _read(path: Path, default: str = "") -> str:
    if not path.exists():
        return default
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _parse_meta_line(line: str) -> tuple[str, str] | None:
    m = re.match(r"^\s*(?:[-*]\s*)?([A-Za-z0-9_\-\u4e00-\u9fff]+)\s*[:：]\s*(.*?)\s*$", line)
    if not m:
        return None
    key = m.group(1).strip().lower()
    value = m.group(2).strip()
    key_map = {
        "标签": "tags",
        "证据": "evidence",
        "动作": "action",
        "行动": "action",
        "置信度": "confidence",
        "可复用": "reusable",
        "状态": "status",
        "严重性": "severity",
        "缓解": "mitigation",
        "复用": "reusable",
    }
    return key_map.get(key, key), value


def _parse_tags(raw: str) -> list[str]:
    text = str(raw or "").strip().strip("[]")
    if not text:
        return []
    parts = re.split(r"[,，、\s]+", text)
    out: list[str] = []
    for p in parts:
        tag = p.strip().strip("'\"`")
        if tag and tag not in out:
            out.append(tag)
    return out


def parse_markdown_entries(path: Path) -> list[MemoryEntry]:
    text = _read(path)
    if not text.strip():
        return []

    matches = list(re.finditer(r"^###\s+(.+?)\s*$", text, flags=re.MULTILINE))
    entries: list[MemoryEntry] = []
    for idx, m in enumerate(matches):
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        heading = m.group(1).strip()
        body = text[start:end].strip()
        meta: dict[str, str] = {}
        for line in body.splitlines():
            parsed = _parse_meta_line(line.strip())
            if parsed:
                meta[parsed[0]] = parsed[1]
        source = path.name
        hash_id = _sha(f"{source}\n{heading}\n{body}")
        entries.append(MemoryEntry(source=source, heading=heading, body=body, meta=meta, hash_id=hash_id))
    return entries


def _truthy(value: str) -> bool:
    v = str(value or "").strip().lower()
    return v in TRUE_VALUES


def _falsey(value: str) -> bool:
    v = str(value or "").strip().lower()
    return v in FALSE_VALUES


def is_reusable(entry: MemoryEntry) -> bool:
    if _truthy(entry.meta.get("reusable", "")):
        return True
    if _truthy(entry.meta.get("active", "")):
        return True
    if entry.source == "errors.md":
        status = entry.meta.get("status", "").strip().lower()
        severity = entry.meta.get("severity", "").strip().lower()
        if status and not _falsey(status):
            return True
        return severity in {"high", "critical", "medium"}
    status = entry.meta.get("status", "").strip().lower()
    return status in {"active", "current", "open"}


def _entry_priority(entry: MemoryEntry) -> tuple[int, int, str]:
    severity = entry.meta.get("severity", "").strip().lower()
    confidence = entry.confidence.lower()
    score = 0
    if entry.source == "errors.md":
        score += 30
    if severity == "critical":
        score += 40
    elif severity == "high":
        score += 30
    elif severity == "medium":
        score += 20
    if confidence == "high":
        score += 20
    elif confidence == "medium":
        score += 10
    if "promotion" in entry.tags:
        score += 10
    if "p2" in entry.tags or "execution" in entry.tags:
        score += 10
    return (-score, -_date_score(entry.heading), entry.title)


def _date_score(text: str) -> int:
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not m:
        return 0
    return int(m.group(1) + m.group(2) + m.group(3))


def select_active_entries(entries: list[MemoryEntry], max_active: int) -> list[MemoryEntry]:
    candidates = [e for e in entries if is_reusable(e)]
    candidates.sort(key=_entry_priority)
    seen: set[str] = set()
    out: list[MemoryEntry] = []
    for entry in candidates:
        key = entry.title.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
        if len(out) >= max_active:
            break
    return out


def _manual_notes(existing_actives: str) -> str:
    marker = "\n## Manual Notes"
    if marker not in existing_actives:
        return "## Manual Notes\n\n- Keep this section for human notes that should not be overwritten by the generator.\n"
    return existing_actives[existing_actives.index(marker) + 1 :].rstrip() + "\n"


def _profile_summary(memory_dir: Path) -> str:
    profile = _read(memory_dir / "profile.md")
    lines = []
    for raw in profile.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- Default profile") or line.startswith("- Main profile") or "Main profile:" in line:
            lines.append(line)
        elif line.startswith("- 20-day") or line.startswith("- Research OOS") or line.startswith("- Do not treat"):
            lines.append(line)
        if len(lines) >= 5:
            break
    return "\n".join(lines)


def render_active_memory(active: list[MemoryEntry], *, memory_dir: Path, existing_actives: str) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    profile_summary = _profile_summary(memory_dir)
    parts = [
        "# Active Memory",
        "",
        f"Generated by `scripts/quant_memory_evolve.py` at `{generated_at}`.",
        "",
        "Read this file at the start of each session after `memory/profile.md`.",
        "",
        AUTO_START,
        "",
        "## Session Boot Context",
        "",
    ]
    if profile_summary:
        parts.append(profile_summary)
        parts.append("")
    parts.extend(
        [
            "## Reusable Strategy And Execution Cards",
            "",
        ]
    )
    if not active:
        parts.append("No reusable active cards were found.")
        parts.append("")
    for idx, entry in enumerate(active, start=1):
        tags = ", ".join(entry.tags) if entry.tags else "none"
        parts.extend(
            [
                f"### A{idx}. {entry.title}",
                f"- source: `{entry.source}` `{entry.hash_id}`",
                f"- tags: {tags}",
                f"- confidence: {entry.confidence}",
            ]
        )
        if entry.evidence:
            parts.append(f"- evidence: {entry.evidence}")
        if entry.action:
            parts.append(f"- action: {entry.action}")
        takeaway = entry._first_non_meta_sentence()
        if takeaway and takeaway != entry.action:
            parts.append(f"- takeaway: {takeaway}")
        parts.append("")
    parts.extend([AUTO_END, "", _manual_notes(existing_actives)])
    return "\n".join(parts).rstrip() + "\n"


def render_nightly_review(
    *,
    active: list[MemoryEntry],
    all_entries: list[MemoryEntry],
    previous_hashes: set[str],
    input_signature: str,
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    active_hashes = {e.hash_id for e in active}
    new_hashes = sorted(active_hashes - previous_hashes)
    errors = [e for e in all_entries if e.source == "errors.md" and is_reusable(e)]
    learning_count = len([e for e in all_entries if e.source == "learnings.md"])

    parts = [
        "# Nightly Memory Review Draft",
        "",
        f"Generated at `{generated_at}` by `scripts/quant_memory_evolve.py`.",
        "",
        "## Summary",
        "",
        f"- long_term_learning_entries: {learning_count}",
        f"- active_cards: {len(active)}",
        f"- active_error_cards: {len(errors)}",
        f"- newly_promoted_active_hashes: {', '.join(new_hashes) if new_hashes else 'none'}",
        f"- input_signature: `{input_signature}`",
        "",
        "## Review Questions",
        "",
        "- Did any fresh P2/shadow/promotion evidence contradict an active memory item?",
        "- Did any candidate win by lower exposure rather than better execution-adjusted alpha?",
        "- Are any active errors now resolved and ready to be marked `status: resolved`?",
        "- Are new learnings specific enough to be reused, with evidence and action fields?",
        "",
        "## Active Cards For Review",
        "",
    ]
    for entry in active:
        parts.append(f"- `{entry.hash_id}` {entry.title} ({entry.source})")
    parts.extend(
        [
            "",
            "## Suggested Commands",
            "",
            "```bash",
            "python scripts/quant_memory_evolve.py",
            "python scripts/quant_profile_promotion_review.py --write-latest",
            "```",
        ]
    )
    return "\n".join(parts).rstrip() + "\n"


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "active_hashes": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": 1, "active_hashes": []}
    return data if isinstance(data, dict) else {"schema_version": 1, "active_hashes": []}


def build_memory(memory_dir: Path, max_active: int) -> tuple[str, str, dict[str, Any]]:
    learning_entries = parse_markdown_entries(memory_dir / "learnings.md")
    error_entries = parse_markdown_entries(memory_dir / "errors.md")
    all_entries = learning_entries + error_entries
    active = select_active_entries(all_entries, max_active=max_active)

    state_path = memory_dir / "state.json"
    state = load_state(state_path)
    previous_hashes = set(str(x) for x in state.get("active_hashes", []))
    active_hashes = [e.hash_id for e in active]
    input_signature = _sha(
        _read(memory_dir / "profile.md")
        + "\n"
        + _read(memory_dir / "learnings.md")
        + "\n"
        + _read(memory_dir / "errors.md")
    )
    existing_actives = _read(memory_dir / "actives.md")
    actives_text = render_active_memory(active, memory_dir=memory_dir, existing_actives=existing_actives)
    review_text = render_nightly_review(
        active=active,
        all_entries=all_entries,
        previous_hashes=previous_hashes,
        input_signature=input_signature,
    )
    next_state = {
        "schema_version": 1,
        "last_run_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "input_signature": input_signature,
        "active_hashes": active_hashes,
        "new_active_hashes": sorted(set(active_hashes) - previous_hashes),
        "learning_entry_count": len(learning_entries),
        "error_entry_count": len(error_entries),
    }
    return actives_text, review_text, next_state


def append_learning(
    *,
    memory_dir: Path,
    title: str,
    tags: str,
    evidence: str,
    action: str,
    confidence: str,
    reusable: str,
    body: str,
) -> None:
    path = memory_dir / "learnings.md"
    now = datetime.now().strftime("%Y-%m-%d")
    entry = [
        "",
        f"### {now} | {title.strip()}",
        f"- tags: {tags.strip()}",
        f"- reusable: {reusable.strip() or 'yes'}",
        f"- confidence: {confidence.strip() or 'medium'}",
    ]
    if evidence.strip():
        entry.append(f"- evidence: {evidence.strip()}")
    if action.strip():
        entry.append(f"- action: {action.strip()}")
    entry.extend(["", body.strip() or title.strip(), ""])
    text = _read(path)
    if "## Learnings Log" not in text:
        text = text.rstrip() + "\n\n## Learnings Log\n"
    _write(path, text.rstrip() + "\n" + "\n".join(entry))


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh project active memory from long-term memory")
    parser.add_argument("--memory-dir", type=str, default=str(MEMORY_DIR), help="memory directory")
    parser.add_argument("--max-active", type=int, default=12, help="maximum active cards")
    parser.add_argument("--dry-run", action="store_true", help="print summary without writing generated files")
    parser.add_argument("--check", action="store_true", help="validate memory files and exit non-zero if missing")
    parser.add_argument("--append-learning", type=str, default="", help="append a learning title before refreshing")
    parser.add_argument("--tags", type=str, default="", help="tags for --append-learning")
    parser.add_argument("--evidence", type=str, default="", help="evidence for --append-learning")
    parser.add_argument("--action", type=str, default="", help="action for --append-learning")
    parser.add_argument("--confidence", type=str, default="medium", help="confidence for --append-learning")
    parser.add_argument("--reusable", type=str, default="yes", help="reusable flag for --append-learning")
    parser.add_argument("--body", type=str, default="", help="body for --append-learning")
    args = parser.parse_args()

    memory_dir = Path(args.memory_dir).resolve()
    required = ["profile.md", "actives.md", "learnings.md", "errors.md"]
    missing = [name for name in required if not (memory_dir / name).exists()]
    if missing:
        print(f"missing memory files: {', '.join(missing)}", file=sys.stderr)
        return 2
    if args.check:
        print(f"memory check ok: {memory_dir}")
        return 0

    if args.append_learning.strip():
        append_learning(
            memory_dir=memory_dir,
            title=args.append_learning,
            tags=args.tags,
            evidence=args.evidence,
            action=args.action,
            confidence=args.confidence,
            reusable=args.reusable,
            body=args.body,
        )

    actives_text, review_text, state = build_memory(memory_dir, max_active=max(1, int(args.max_active)))
    if args.dry_run:
        print(
            json.dumps(
                {
                    "memory_dir": str(memory_dir),
                    "active_count": len(state.get("active_hashes", [])),
                    "new_active_hashes": state.get("new_active_hashes", []),
                    "input_signature": state.get("input_signature", ""),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    _write(memory_dir / "actives.md", actives_text)
    _write(memory_dir / "nightly_review_draft.md", review_text)
    _write(memory_dir / "state.json", json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "memory_dir": str(memory_dir),
                "active_count": len(state.get("active_hashes", [])),
                "new_active_hashes": state.get("new_active_hashes", []),
                "actives": str(memory_dir / "actives.md"),
                "nightly_review": str(memory_dir / "nightly_review_draft.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
