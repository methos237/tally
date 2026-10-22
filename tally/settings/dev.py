from .base import *  # noqa: F403

DEBUG = True

from tally.logging import configure as _configure_logging  # noqa: E402

_configure_logging(json=False)
