from celery import Celery

from townlight_records.config import settings

celery_app = Celery(
    "townlight_records",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
)


@celery_app.task(name="townlight_records.health")
def health_check():
    return {"status": "ok"}


# Import tasks so Celery discovers them
import townlight_records.ingestion.tasks  # noqa: F401, E402
import townlight_records.ingestion.scheduler  # noqa: F401, E402
