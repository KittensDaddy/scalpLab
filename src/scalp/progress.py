from __future__ import annotations
from dataclasses import dataclass
import sys, time
from typing import Callable

ProgressCallback = Callable[[float, str], None]

def emit_progress(callback: ProgressCallback | None, percent: float, message: str) -> None:
    if callback is None:
        return
    callback(max(0.0, min(100.0, float(percent))), str(message))

def map_progress(callback: ProgressCallback | None, start: float, end: float) -> ProgressCallback | None:
    if callback is None:
        return None
    span = float(end) - float(start)
    return lambda pct, msg: emit_progress(callback, float(start) + span * float(pct) / 100.0, msg)

@dataclass
class ConsoleProgress:
    """Dependency-free terminal progress bar written to stderr.

    JSON/result output remains clean on stdout, while long research jobs visibly
    advance in an interactive shell or journal.
    """
    width: int = 28
    stream: object = sys.stderr

    def __post_init__(self):
        self.started = time.monotonic()
        self.last_percent = -1
        self.last_message = ""
        self.finished = False

    @staticmethod
    def _elapsed(seconds: float) -> str:
        seconds = max(0, int(seconds))
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    def __call__(self, percent: float, message: str) -> None:
        p = int(max(0, min(100, round(percent))))
        # Avoid redrawing the same line hundreds of times unless the stage changed.
        if p == self.last_percent and message == self.last_message and p < 100:
            return
        self.last_percent, self.last_message = p, message
        filled = int(self.width * p / 100)
        bar = "█" * filled + "░" * (self.width - filled)
        elapsed = self._elapsed(time.monotonic() - self.started)
        text = f"\r[{bar}] {p:3d}%  {elapsed}  {message[:72]:<72}"
        print(text, end="", file=self.stream, flush=True)
        if p >= 100 and not self.finished:
            print(file=self.stream, flush=True)
            self.finished = True
