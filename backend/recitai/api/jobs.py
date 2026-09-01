"""In-process job registry for background generation (spec §12).

Generation takes minutes, so `POST /quizzes` returns 202 with a job id and the client
polls (§12). Celery + Redis is §16 task 2; until then jobs live in this process, which is
correct for a single-instance deployment and honest about its limits: a restart loses
in-flight jobs, and nothing is shared between workers.
"""

import asyncio
import uuid
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

import structlog

log = structlog.get_logger(__name__)

JobStatus = Literal["queued", "running", "complete", "failed"]


@dataclass
class Job:
    id: uuid.UUID
    status: JobStatus = "queued"
    detail: str = ""
    progress: int = 0
    total: int = 0
    result_id: uuid.UUID | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, object]:
        return {
            "job_id": str(self.id),
            "status": self.status,
            "detail": self.detail,
            "progress": self.progress,
            "total": self.total,
            "result_id": str(self.result_id) if self.result_id else None,
            "error": self.error,
        }


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[uuid.UUID, Job] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def create(self, total: int = 0) -> Job:
        job = Job(id=uuid.uuid4(), total=total)
        self._jobs[job.id] = job
        return job

    def get(self, job_id: uuid.UUID) -> Job | None:
        return self._jobs.get(job_id)

    def spawn(self, job: Job, coro: Coroutine[object, object, None]) -> None:
        """Run a job, recording failure on the job rather than losing it to the void."""

        async def runner() -> None:
            job.status = "running"
            try:
                await coro
                if job.status == "running":
                    job.status = "complete"
            except Exception as exc:  # noqa: BLE001 - recorded on the job and re-logged
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                log.error("job.failed", job_id=str(job.id), error=job.error)

        task = asyncio.create_task(runner())
        # Keep a reference: a task with no strong reference can be garbage collected
        # mid-flight, which looks exactly like a job that silently never ran.
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


registry = JobRegistry()
