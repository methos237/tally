from .base import *  # noqa: F403

# Argon2 stays on in tests: the hasher is part of what is under test and keys are few.
CELERY_TASK_ALWAYS_EAGER = True

# Separate Redis database so test flushes never touch dev buckets.
TEST_REDIS_URL = REDIS_URL.rsplit("/", 1)[0] + "/1"  # noqa: F405
CACHES = {"default": {"BACKEND": "django_redis.cache.RedisCache", "LOCATION": TEST_REDIS_URL}}
