"""数据版本化与运行可复现清单。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import json
from pathlib import Path
import uuid


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _json_default(obj):
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Unsupported type: {type(obj)!r}")


@dataclass
class FileVersion:
    path: str
    exists: bool
    size_bytes: int = 0
    mtime: str = ""
    sha256: str = ""


@dataclass
class RunManifest:
    run_id: str
    run_type: str
    created_at: str
    status: str
    argv: list[str] = field(default_factory=list)
    params: dict[str, object] = field(default_factory=dict)
    versions: dict[str, FileVersion] = field(default_factory=dict)
    config_fingerprint: str = ""
    step_results: dict[str, object] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    finished_at: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["versions"] = {k: asdict(v) for k, v in self.versions.items()}
        return payload


def build_file_version(path: str | Path) -> FileVersion:
    p = Path(path)
    if not p.exists():
        return FileVersion(path=str(p), exists=False)
    stat = p.stat()
    return FileVersion(
        path=str(p),
        exists=True,
        size_bytes=int(stat.st_size),
        mtime=datetime.fromtimestamp(stat.st_mtime).isoformat(),
        sha256=_sha256_file(p),
    )


def build_run_manifest(
    *,
    run_type: str,
    argv: list[str] | None = None,
    params: dict[str, object] | None = None,
    tracked_files: dict[str, str | Path] | None = None,
    config_fingerprint: str = "",
) -> RunManifest:
    now = datetime.now()
    run_id = f"{run_type}_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    versions = {name: build_file_version(path) for name, path in (tracked_files or {}).items()}
    return RunManifest(
        run_id=run_id,
        run_type=str(run_type),
        created_at=now.isoformat(),
        status="running",
        argv=list(argv or []),
        params=dict(params or {}),
        versions=versions,
        config_fingerprint=str(config_fingerprint or ""),
    )


def write_run_manifest(base_dir: str | Path, manifest: RunManifest) -> Path:
    out_dir = Path(base_dir) / "output" / "platform" / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{manifest.run_id}.json"
    path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    return path


def finalize_run_manifest(
    manifest_path: str | Path,
    *,
    status: str,
    step_results: dict[str, object] | None = None,
    notes: list[str] | None = None,
) -> dict[str, object]:
    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["status"] = str(status)
    payload["finished_at"] = datetime.now().isoformat()
    if step_results is not None:
        payload["step_results"] = dict(step_results)
    if notes is not None:
        payload["notes"] = list(notes)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def load_latest_run_manifest(base_dir: str | Path) -> dict[str, object] | None:
    run_dir = Path(base_dir) / "output" / "platform" / "runs"
    if not run_dir.exists():
        return None
    files = sorted(run_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))
