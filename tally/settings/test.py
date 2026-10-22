from .base import *  # noqa: F403

# Same Argon2 algorithm, minimum cost: production parameters are ~26 ms and 100 MiB per
# verify, and the API suite verifies a key on every request.
PASSWORD_HASHERS = ["tally.settings.test.FastArgon2"]
CELERY_TASK_ALWAYS_EAGER = True

# Separate Redis database so test flushes never touch dev buckets.
TEST_REDIS_URL = REDIS_URL.rsplit("/", 1)[0] + "/1"  # noqa: F405
CACHES = {"default": {"BACKEND": "django_redis.cache.RedisCache", "LOCATION": TEST_REDIS_URL}}


from django.contrib.auth.hashers import Argon2PasswordHasher  # noqa: E402


class FastArgon2(Argon2PasswordHasher):
    time_cost = 1
    memory_cost = 8
    parallelism = 1
