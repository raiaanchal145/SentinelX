"""SentinelX background worker (docs/DECISIONS.md -- Arq over RQ).

The API enqueues jobs through app.worker.queue; the worker process is
started by the dev launcher's third terminal (`arq app.worker.WorkerSettings`)
or manually with:

    cd backend && .venv/Scripts/python -m arq app.worker.WorkerSettings

Jobs live in app.worker.jobs and must be registered in JOB_FUNCTIONS so
enqueue_work() can find them by name.
"""

from app.worker.jobs import JOB_FUNCTIONS, WorkerSettings  # noqa: F401
