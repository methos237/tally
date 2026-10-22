import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tally.settings.dev")
app = Celery("tally")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
