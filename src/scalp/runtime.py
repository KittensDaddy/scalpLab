from __future__ import annotations

import os
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX
    resource = None

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


def ensure_nofile_limit(target: int = 8192) -> dict[str, Any]:
    """Best-effort raise of this process' soft file-descriptor limit.

    ScalpLab uses HTTP, WebSocket and market-data sockets concurrently. A low
    shell/systemd RLIMIT_NOFILE (often 1024) can turn a burst of connections
    into EMFILE/"Too many open files". We never exceed the configured hard
    limit and we report the effective result for diagnostics.
    """
    if resource is None:
        return {"supported": False, "soft": None, "hard": None, "changed": False}
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    old_soft = soft
    infinity = getattr(resource, "RLIM_INFINITY", -1)
    ceiling = target if hard == infinity else hard
    desired = min(max(int(soft), int(target)), int(ceiling))
    if desired > soft:
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (desired, hard))
            soft = desired
        except (OSError, ValueError, PermissionError):
            soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    return {"supported": True, "soft": int(soft), "hard": int(hard) if hard != infinity else "unlimited", "changed": soft > old_soft}


def fd_stats() -> dict[str, Any]:
    """Current process descriptor usage for the Web UI/doctor."""
    count = None
    if psutil is not None:
        try:
            proc = psutil.Process(os.getpid())
            if hasattr(proc, "num_fds"):
                count = int(proc.num_fds())
            elif hasattr(proc, "num_handles"):
                count = int(proc.num_handles())
        except Exception:
            pass
    if count is None:
        try:
            count = len(os.listdir("/proc/self/fd"))
        except Exception:
            pass

    soft = hard = None
    if resource is not None:
        try:
            soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            infinity = getattr(resource, "RLIM_INFINITY", -1)
            hard = "unlimited" if hard == infinity else int(hard)
            soft = int(soft)
        except Exception:
            soft = hard = None
    used_pct = (count / soft * 100.0) if count is not None and soft else None
    state = "OK"
    if used_pct is not None:
        if used_pct >= 90:
            state = "CRITICAL"
        elif used_pct >= 70:
            state = "WARNING"
    return {"pid": os.getpid(), "open_fds": count, "soft_limit": soft, "hard_limit": hard, "used_pct": used_pct, "state": state}
