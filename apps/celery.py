import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "apps.settings")

from django.conf import settings  # noqa: E402  (po ustawieniu DJANGO_SETTINGS_MODULE)

celery_rabbit = Celery(
    'rabbit_tasks',
    broker=settings.RABBITMQ_BROKER_URL,
    set_as_current=False,
    include=[
        'apps.app.tasks.tasks_rabbit',
    ],
)

celery_rabbit.config_from_object("django.conf:settings", namespace="CELERY")
celery_rabbit.conf.task_default_queue = 'rabbit_tasks'



celery_redis = Celery(
    "redis_tasks",
    broker=settings.REDIS_BROKER_URL,
    set_as_current=False,
    include=[
        'apps.app.tasks.tasks_redis',
    ],
)
celery_redis.config_from_object("django.conf:settings", namespace="CELERY")
celery_redis.conf.task_default_queue = 'redis_tasks'
