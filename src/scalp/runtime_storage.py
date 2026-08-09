from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path


FORBIDDEN_NAMES = {".venv", "venv"}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def validate_runtime_root(value: str | Path, source_root: Path | None = None) -> Path:
    raw = str(value).strip()
    if not raw:
        raise ValueError("runtime_root is required")
    path = Path(raw).expanduser().resolve()
    project = (source_root or _project_root()).resolve()
    if path == Path(path.anchor) or path == project or project in path.parents:
        raise ValueError("runtime_root cannot be / or inside the source tree")
    if any(part.lower() in FORBIDDEN_NAMES for part in path.parts):
        raise ValueError("runtime_root cannot be a virtual environment")
    return path


@dataclass(frozen=True)
class RuntimeLayout:
    root: Path

    @property
    def raw(self): return self.root / "raw"
    @property
    def features(self): return self.root / "features"
    @property
    def cache(self): return self.root / "cache"
    @property
    def state(self): return self.root / "state"
    @property
    def results(self): return self.root / "results"
    @property
    def universes(self): return self.root / "universes"
    @property
    def strategies(self): return self.root / "strategies"

    def ensure(self):
        for p in (self.raw, self.features, self.cache, self.state, self.results, self.universes, self.strategies):
            p.mkdir(parents=True, exist_ok=True)
        return self


class RuntimeRootManager:
    """Persistent runtime-root pointer and conservative staged migration."""

    def __init__(self, pointer: str | Path | None = None, default: str | Path | None = None):
        self.pointer = Path(pointer or os.getenv("SCALP_RUNTIME_POINTER", "config/runtime.json"))
        self.default = Path(default or os.getenv("SCALP_RUNTIME_ROOT", "data/runtime")).resolve()
        self._lock = threading.Lock()

    def current(self) -> RuntimeLayout:
        root = self.default
        if self.pointer.exists():
            try: root = Path(json.loads(self.pointer.read_text())["runtime_root"])
            except (OSError, ValueError, KeyError, TypeError): pass
        return RuntimeLayout(root.resolve()).ensure()

    def estimate(self) -> dict:
        root = self.current().root
        files = bytes_ = 0
        if root.exists():
            for p in root.rglob("*"):
                if p.is_file():
                    files += 1
                    try: bytes_ += p.stat().st_size
                    except OSError: pass
        return {"files": files, "bytes": bytes_}

    def validate(self, destination: str | Path) -> dict:
        path = validate_runtime_root(destination)
        path.mkdir(parents=True, exist_ok=True)
        probe = None
        try:
            fd, name = tempfile.mkstemp(prefix=".scalp-write-", dir=path)
            os.close(fd); probe = Path(name); probe.unlink()
        except OSError as exc:
            raise ValueError(f"destination is not writable: {exc}") from exc
        usage = shutil.disk_usage(path)
        estimate = self.estimate()
        required = int(estimate["bytes"] * 1.05)
        return {"path": str(path), "writable": True, "free_bytes": usage.free,
                "required_bytes": required, "sufficient_space": usage.free >= required, **estimate}

    def migrate(self, destination: str | Path, jobs_running: bool = False) -> dict:
        if jobs_running:
            raise RuntimeError("recorder, shadow, and research jobs must be stopped before migration")
        with self._lock:
            source = self.current().root
            check = self.validate(destination)
            if not check["sufficient_space"]:
                raise RuntimeError("insufficient destination capacity")
            dest = Path(check["path"])
            if dest == source:
                return {"status": "UNCHANGED", "runtime_root": str(source)}
            stage = dest.parent / f".{dest.name}.scalp-staging"
            if stage.exists():
                shutil.rmtree(stage)
            shutil.copytree(source, stage, copy_function=shutil.copy2)
            self._verify(source, stage)
            if dest.exists() and any(dest.iterdir()):
                raise RuntimeError("destination must be empty")
            if dest.exists(): dest.rmdir()
            os.replace(stage, dest)
            self.pointer.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.pointer.with_suffix(".tmp")
            tmp.write_text(json.dumps({"runtime_root": str(dest)}, indent=2))
            os.replace(tmp, self.pointer)
            return {"status": "COMPLETE", "runtime_root": str(dest),
                    "recovery_root": str(source), "old_data_retained": True}

    @staticmethod
    def _verify(source: Path, target: Path):
        def inventory(root):
            vals = []
            for p in root.rglob("*"):
                if p.is_file(): vals.append((str(p.relative_to(root)), p.stat().st_size))
            return sorted(vals)
        if inventory(source) != inventory(target):
            raise RuntimeError("staged copy verification failed")
        for db in target.rglob("*.db"):
            with sqlite3.connect(db) as conn:
                result = conn.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok": raise RuntimeError(f"SQLite integrity failed: {db}")


runtime_roots = RuntimeRootManager()
