"""Minimal background job manager so long solves never block the API."""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"  # queued | running | done | error
    progress: float = 0.0
    message: str = "Queued"
    result: Any = None
    error: str | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None

    def view(self, include_result: bool = True) -> dict[str, Any]:
        d = {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "progress": round(self.progress, 4),
            "message": self.message,
            "error": self.error,
            "elapsed_s": round((self.finished or time.time()) - self.created, 3),
        }
        if include_result and self.status == "done":
            d["result"] = self.result
        return d


class JobManager:
    def __init__(self, workers: int = 2, keep: int = 100):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="kairos-job")
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._lock = threading.Lock()
        self._keep = keep

    def submit(self, kind: str, fn: Callable[..., Any], **kwargs: Any) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job
            while len(self._jobs) > self._keep:
                self._jobs.popitem(last=False)

        def progress(frac: float, msg: str) -> None:
            job.progress = max(job.progress, min(1.0, float(frac)))
            job.message = msg

        def run() -> None:
            job.status, job.message = "running", "Starting"
            try:
                job.result = fn(progress=progress, **kwargs)
                job.status, job.progress, job.message = "done", 1.0, "Complete"
            except (ValueError, KeyError) as exc:
                job.status, job.error = "error", str(exc).strip("'\"")
            except Exception as exc:  # noqa: BLE001 - surfaced to the client, logged
                traceback.print_exc()
                job.status, job.error = "error", f"{type(exc).__name__}: {exc}"
            finally:
                job.finished = time.time()

        self._pool.submit(run)
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            return self._jobs[job_id]
