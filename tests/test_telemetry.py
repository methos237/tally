from tally.telemetry import exports_spans


def test_only_span_producing_processes_export() -> None:
    assert exports_spans(["manage.py", "runserver", "8001"])
    assert exports_spans(["/x/.venv/bin/celery", "-A", "tally", "worker", "--pool", "solo"])
    assert exports_spans(["gunicorn", "tally.wsgi"])
    assert not exports_spans(["manage.py", "migrate"])
    assert not exports_spans(["manage.py", "seed_demo"])
    assert not exports_spans(["/x/.venv/bin/celery", "-A", "tally", "beat"])
