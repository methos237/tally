import os

from .base import *  # noqa: F403

DEBUG = True
# The Airflow container (compose profile batch) reaches Django on the host by this name.
ALLOWED_HOSTS = [*ALLOWED_HOSTS, "host.docker.internal"]  # noqa: F405
# The Vite dev server proxies /api and /console but keeps its own Origin header.
CSRF_TRUSTED_ORIGINS = ["http://localhost:5173"]
TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")

from tally.logging import configure as _configure_logging  # noqa: E402

_configure_logging(json=False)
