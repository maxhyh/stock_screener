"""Output 路径工具：支持分层目录与旧路径兼容。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

OUTPUT_SUBDIRS = {
    "scan": "scan",
    "daily": "daily",
    "verify": "verify",
    "backtest": "backtest",
}


def ensure_output_dirs(output_dir: str | Path) -> dict[str, Path]:
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    dirs = {k: base / v for k, v in OUTPUT_SUBDIRS.items()}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def get_output_dirs(output_dir: str | Path) -> dict[str, Path]:
    base = Path(output_dir)
    return {"base": base, **{k: base / v for k, v in OUTPUT_SUBDIRS.items()}}


def write_dual_csv(df, new_path: Path, legacy_path: Path, **kwargs) -> tuple[Path, Path]:
    new_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(new_path, **kwargs)
    if legacy_path.resolve() != new_path.resolve():
        df.to_csv(legacy_path, **kwargs)
    return new_path, legacy_path


def resolve_file(new_path: Path, legacy_path: Path) -> Path | None:
    if new_path.exists():
        return new_path
    if legacy_path.exists():
        return legacy_path
    return None


def list_dual(glob_patterns: Iterable[str], new_dir: Path, legacy_dir: Path) -> list[Path]:
    files: dict[Path, Path] = {}
    for pat in glob_patterns:
        for p in new_dir.glob(pat):
            files[p.resolve()] = p
        for p in legacy_dir.glob(pat):
            files[p.resolve()] = p
    return sorted(files.values())
