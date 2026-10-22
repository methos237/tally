import os

from hypothesis import settings

settings.register_profile("ci", max_examples=1000, deadline=None)
settings.register_profile("dev", max_examples=100)
settings.load_profile("ci" if os.environ.get("CI") else "dev")
