"""平台级 profiling 与基线工具。"""

from __future__ import annotations

from dataclasses import dataclass
import time
import tracemalloc
from typing import Any, Callable


@dataclass
class ProfileResult:
    label: str
    iterations: int
    elapsed_seconds: float
    avg_seconds: float
    peak_memory_kb: float


def profile_call(
    label: str,
    func: Callable[..., Any],
    *args,
    iterations: int = 1,
    warmup: int = 0,
    **kwargs,
) -> ProfileResult:
    for _ in range(max(int(warmup), 0)):
        func(*args, **kwargs)

    tracemalloc.start()
    started = time.perf_counter()
    for _ in range(max(int(iterations), 1)):
        func(*args, **kwargs)
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return ProfileResult(
        label=str(label),
        iterations=max(int(iterations), 1),
        elapsed_seconds=float(elapsed),
        avg_seconds=float(elapsed / max(int(iterations), 1)),
        peak_memory_kb=float(peak / 1024.0),
    )
