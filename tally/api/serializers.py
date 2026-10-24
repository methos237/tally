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


class ProblemOut(serializers.Serializer[Any]):
    """RFC 9457 body every error carries; see tally.api.problems."""

    type = serializers.URLField()
    title = serializers.CharField()
    status = serializers.IntegerField()
    detail = serializers.CharField()


class MeOut(serializers.Serializer[Any]):
    tenant_id = serializers.IntegerField()
    tenant = serializers.CharField()


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
    balance = serializers.SerializerMethodField()

    class Meta:
        model = models.Account
        fields = ["id", "code", "name", "type", "currency", "balance"]

    def get_balance(self, account: models.Account) -> str:
        row = getattr(account, "balance", None)  # the projection row; absent until first post
        return str(row.balance if row else Decimal(0).quantize(Decimal("0.000001")))


class BalanceOut(serializers.Serializer[Any]):
    account = serializers.CharField()
    currency = serializers.CharField()
    balance = AmountField()
    as_of = serializers.DateTimeField(allow_null=True)


class WebhookEndpointIn(serializers.Serializer[Any]):
    url = serializers.URLField(max_length=500)


class WebhookEndpointOut(serializers.ModelSerializer[models.WebhookEndpoint]):
    dead_letters = serializers.SerializerMethodField()

    class Meta:
        model = models.WebhookEndpoint
        fields = ["id", "url", "created_at", "disabled_at", "dead_letters"]

    def get_dead_letters(self, endpoint: models.WebhookEndpoint) -> int:
        return int(getattr(endpoint, "dead_letters", 0))  # annotated by the list view


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


class SubscriptionOut(serializers.ModelSerializer[models.Subscription]):
    customer = serializers.CharField(source="customer.name")
    plan = serializers.CharField(source="plan.code")
    plan_name = serializers.CharField(source="plan.name")
    amount = AmountField(source="plan.amount")
    currency = serializers.ChoiceField(choices=CURRENCIES, source="plan.currency")
    interval = serializers.ChoiceField(choices=["month", "year"], source="plan.interval")
    status = serializers.ChoiceField(choices=["active", "past_due", "canceled"])

    class Meta:
        model = models.Subscription
        fields = [
            "id",
            "customer",
            "plan",
            "plan_name",
            "amount",
            "currency",
            "interval",
            "status",
            "started_at",
            "billed_through",
        ]


class InvoiceOut(serializers.ModelSerializer[models.Invoice]):
    customer = serializers.CharField(source="subscription.customer.name")
    status = serializers.ChoiceField(choices=["open", "paid"])

    class Meta:
        model = models.Invoice
        fields = [
            "id",
            "subscription",
            "customer",
            "description",
            "period_start",
            "period_end",
            "amount",
            "currency",
            "status",
            "issued_at",
            "paid_at",
        ]


class ReportOut(serializers.Serializer[Any]):
    day = serializers.DateField()
    key = serializers.CharField()
    size = serializers.IntegerField()
    last_modified = serializers.DateTimeField()


class ExceptionOut(serializers.ModelSerializer[models.ReconciliationException]):
    line_no = serializers.IntegerField(source="line.line_no")
    reference = serializers.CharField(source="line.reference")
    entry = serializers.PrimaryKeyRelatedField[models.JournalEntry](read_only=True)
    adjusting_entry = serializers.PrimaryKeyRelatedField[models.JournalEntry](read_only=True)

    class Meta:
        model = models.ReconciliationException
        fields = [
            "id",
            "statement",
            "line_no",
            "reference",
            "reason",
            "difference",
            "currency",
            "entry",
            "created_at",
            "resolved_at",
            "resolution",
            "adjusting_entry",
            "explanation",
        ]


class StatementLineOut(serializers.ModelSerializer[models.StatementLine]):
    matched_entry = serializers.PrimaryKeyRelatedField[models.JournalEntry](read_only=True)

    class Meta:
        model = models.StatementLine
        fields = [
            "line_no",
            "occurred_on",
            "amount",
            "currency",
            "reference",
            "description",
            "matched_entry",
            "match_rule",
        ]


class StatementSummaryOut(serializers.ModelSerializer[models.Statement]):
    class Meta:
        model = models.Statement
        fields = ["id", "source", "period_start", "period_end", "uploaded_at", "reconciled_at"]


class StatementOut(StatementSummaryOut):
    lines = StatementLineOut(many=True)
    exceptions = ExceptionOut(many=True)

    class Meta(StatementSummaryOut.Meta):
        fields = [*StatementSummaryOut.Meta.fields, "lines", "exceptions"]


class ResolveIn(serializers.Serializer[Any]):
    action = serializers.ChoiceField(choices=["adjust", "explain"])
    account = serializers.CharField(max_length=32, required=False, help_text="for adjust")
    explanation = serializers.CharField(required=False, help_text="for explain")

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        needed = "account" if data["action"] == "adjust" else "explanation"
        if not data.get(needed):
            raise serializers.ValidationError({needed: f"required when action is {data['action']}"})
        return data
