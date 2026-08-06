from celery import Celery

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery("job_graph", broker=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_backend=None,
    timezone="UTC",
    beat_schedule={
        "redispatch-pending-runs": {
            "task": "app.redispatch_pending_runs",
            "schedule": 60.0,
        },
        "mark-stale-runs": {
            "task": "app.mark_stale_runs",
            "schedule": 60.0,
        },
        "clean-expired-sessions-hourly": {
            "task": "app.clean_expired_sessions",
            "schedule": 3600.0,
        },
        "clean-unattached-files-daily": {
            "task": "app.clean_unattached_files",
            "schedule": 86400.0,
        },
    },
)
celery_app.autodiscover_tasks(["app.processing", "app.imports", "app.discovery"])
