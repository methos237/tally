from .base import *  # noqa: F403

DEBUG = True
# The Airflow container (compose profile batch) reaches Django on the host by this name.
ALLOWED_HOSTS = [*ALLOWED_HOSTS, "host.docker.internal"]  # noqa: F405

from tally.logging import configure as _configure_logging  # noqa: E402

_configure_logging(json=False)
