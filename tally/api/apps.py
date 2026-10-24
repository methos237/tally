from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = "tally.api"
    label = "api"

    def ready(self) -> None:
        from prometheus_client import REGISTRY

        from tally import telemetry
        from tally.adapters.metrics import TallyCollector

        telemetry.configure()
        REGISTRY.register(TallyCollector())
