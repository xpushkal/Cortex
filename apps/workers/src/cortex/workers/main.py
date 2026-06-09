"""arq worker entrypoint. Run with `arq cortex.workers.main.WorkerSettings`.

The functions list and Redis settings are populated as the pipeline lands (M0+).
"""

from __future__ import annotations

from typing import ClassVar


class WorkerSettings:
    """arq worker configuration. Stub — functions/queues wired in M0."""

    functions: ClassVar[list[object]] = []
    # redis_settings, queue_name, max_jobs, etc. configured in M0.
