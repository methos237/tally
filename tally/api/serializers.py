"""Wire format. Amounts travel as strings with six decimal places, never floats."""

from decimal import Decimal
from typing import Any

from rest_framework import serializers

from tally.adapters import models
from tally.domain.money import Currency

CURRENCIES = [c.value for c in Currency]


class AmountField(serializers.DecimalField):
    """numeric(18,6) on the wire as a string. A JSON number is refused: floats never touch money."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(max_digits=18, decimal_places=6, **kwargs)

    def to_internal_value(self, data: int | float | str | Decimal) -> Decimal:
        if not isinstance(data, str):
            self.fail("invalid")  # a JSON number, int or float, never reaches Decimal
        return super().to_internal_value(data)


class LineIn(serializers.Serializer[Any]):
    account = serializers.CharField(max_length=32, help_text="account code, e.g. 1200")
    amount = AmountField()
    currency = serializers.ChoiceField(choices=CURRENCIES)


class SourceIn(serializers.Serializer[Any]):
    type = serializers.CharField(max_length=64)
    id = serializers.CharField(max_length=128)


class EntryIn(serializers.Serializer[Any]):
    occurred_at = serializers.DateTimeField()
    source = SourceIn()  # type: ignore[assignment]
    lines = LineIn(many=True, allow_empty=False)


class ReverseIn(serializers.Serializer[Any]):
    occurred_at = serializers.DateTimeField(required=False)


class LineOut(serializers.ModelSerializer[models.JournalLine]):
    account = serializers.CharField(source="account.code")

    class Meta:
        model = models.JournalLine
        fields = ["account", "amount", "currency"]


class EntryOut(serializers.ModelSerializer[models.JournalEntry]):
    source = serializers.SerializerMethodField()  # type: ignore[assignment]
    lines = LineOut(many=True)
    reverses = serializers.PrimaryKeyRelatedField[models.JournalEntry](read_only=True)
    reversed_by = serializers.PrimaryKeyRelatedField[models.JournalEntry](read_only=True)

    class Meta:
        model = models.JournalEntry
        fields = ["id", "occurred_at", "posted_at", "source", "lines", "reverses", "reversed_by"]

    def get_source(self, entry: models.JournalEntry) -> dict[str, str]:
        return {"type": entry.source_type, "id": entry.source_id}


class AccountOut(serializers.ModelSerializer[models.Account]):
    class Meta:
        model = models.Account
        fields = ["id", "code", "name", "type", "currency"]


class BalanceOut(serializers.Serializer[Any]):
    account = serializers.CharField()
    currency = serializers.CharField()
    balance = AmountField()
    as_of = serializers.DateTimeField(allow_null=True)


class WebhookEndpointIn(serializers.Serializer[Any]):
    url = serializers.URLField(max_length=500)


class WebhookEndpointOut(serializers.ModelSerializer[models.WebhookEndpoint]):
    class Meta:
        model = models.WebhookEndpoint
        fields = ["id", "url", "created_at", "disabled_at"]


class WebhookEndpointCreated(WebhookEndpointOut):
    """The secret appears here and nowhere else."""

    class Meta(WebhookEndpointOut.Meta):
        fields = [*WebhookEndpointOut.Meta.fields, "secret"]


class DeadLetterOut(serializers.ModelSerializer[models.OutboxMessage]):
    class Meta:
        model = models.OutboxMessage
        fields = [
            "id",
            "event_type",
            "payload",
            "created_at",
            "attempts",
            "last_status",
            "last_error",
            "dead_at",
        ]
