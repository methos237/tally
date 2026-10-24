from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = "tally.api"
    label = "api"

    def ready(self) -> None:
        from tally import telemetry

        telemetry.configure()
