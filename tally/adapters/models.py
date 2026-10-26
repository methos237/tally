"""Django models for the ledger. Every table carries tenant_id.

journal_entries and journal_lines are append-only; see migration 0002 for
the triggers that enforce it and the deferred balancing check.
"""

from secrets import token_urlsafe

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from tally.domain.billing import Interval, InvoiceStatus, SubscriptionStatus
from tally.domain.journal import AccountType
from tally.domain.money import Currency

CURRENCY_CHOICES = [(c.value, c.value) for c in Currency]


class Tenant(models.Model):
    name = models.CharField(max_length=200, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    rate_limit_per_minute = models.PositiveIntegerField(
        null=True, blank=True, help_text="Overrides RATE_LIMIT_PER_MINUTE for this tenant's keys"
    )
    is_authenticated = True  # a Tenant is the API principal (request.user); see tally.api.auth

    class Meta:
        db_table = "tenants"


class Account(models.Model):
    tenant = models.ForeignKey(
        Tenant, on_delete=models.PROTECT, related_name="accounts", db_index=False
    )
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=200)
    type = models.CharField(max_length=16, choices=[(t.value, t.value) for t in AccountType])
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)

    class Meta:
        db_table = "accounts"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uq_account_tenant_code")
        ]


class JournalEntry(models.Model):
    tenant = models.ForeignKey(
        Tenant, on_delete=models.PROTECT, related_name="entries", db_index=False
    )
    occurred_at = models.DateTimeField()
    posted_at = models.DateTimeField(auto_now_add=True)
    source_type = models.CharField(max_length=64)
    source_id = models.CharField(max_length=128)
    idempotency_key = models.CharField(max_length=255, null=True, blank=True)
    # {"base": "USD", "rates": {"EUR": "1.08"}} for a multi-currency entry; see domain.Conversion
    conversion = models.JSONField(null=True, blank=True)
    reverses = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_by"
    )

    class Meta:
        db_table = "journal_entries"
        indexes = [
            models.Index(fields=["tenant", "occurred_at"], name="ix_entries_tenant_occurred"),
            models.Index(
                fields=["tenant", "source_type", "source_id"], name="ix_entries_tenant_source"
            ),
        ]


class JournalLine(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="+", db_index=False)
    entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="lines")
    amount = models.DecimalField(max_digits=18, decimal_places=6)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)

    class Meta:
        db_table = "journal_lines"
        indexes = [models.Index(fields=["tenant", "account"], name="ix_lines_tenant_account")]
        constraints = [
            models.CheckConstraint(condition=~models.Q(amount=0), name="ck_line_amount_nonzero")
        ]


class ExchangeRate(models.Model):
    """One unit of `currency` is worth `rate` units of `base` on `as_of`. The posting API
    fills a Conversion from the latest row at or before the entry's day."""

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="rates")
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    base = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    rate = models.DecimalField(max_digits=18, decimal_places=8)
    as_of = models.DateField()

    class Meta:
        db_table = "exchange_rates"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "currency", "base", "as_of"], name="uq_rate_tenant_pair_day"
            )
        ]


class AccountBalance(models.Model):
    """Projection: running balance per account, folded from journal_lines.

    Updated incrementally on every post; rebuilt from scratch by
    `manage.py replay_balances`. Never the source of truth.
    """

    account = models.OneToOneField(
        Account, primary_key=True, on_delete=models.PROTECT, related_name="balance"
    )
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="+")
    balance = models.DecimalField(max_digits=18, decimal_places=6)
    as_of = models.DateTimeField(help_text="posted_at of the last entry folded in")

    class Meta:
        db_table = "account_balances"


class ApiKey(models.Model):
    """A tenant credential. The secret is hashed with Argon2; only the prefix is stored
    in the clear so a presented key can be looked up before the hash is checked."""

    PREFIX = "tk_"
    PREFIX_LEN = 8

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="api_keys")
    name = models.CharField(max_length=100)
    prefix = models.CharField(max_length=PREFIX_LEN, unique=True)
    key_hash = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "api_keys"

    @classmethod
    def issue(cls, tenant: Tenant, name: str) -> str:
        """Create a key and return the plaintext, which is shown exactly once."""
        secret = token_urlsafe(32)
        plaintext = f"{cls.PREFIX}{secret}"
        cls.objects.create(
            tenant=tenant,
            name=name,
            prefix=secret[: cls.PREFIX_LEN],
            key_hash=make_password(plaintext, hasher="argon2"),
        )
        return plaintext

    @classmethod
    def authenticate(cls, plaintext: str) -> "ApiKey | None":
        """The live key matching `plaintext`, or None."""
        if not plaintext.startswith(cls.PREFIX):
            return None
        prefix = plaintext.removeprefix(cls.PREFIX)[: cls.PREFIX_LEN]
        row = (
            cls.objects.filter(prefix=prefix, revoked_at__isnull=True)
            .select_related("tenant")
            .first()
        )
        # ponytail: one Argon2 verify (~26 ms) per request; cache verified keys in Redis if needed
        return row if row and check_password(plaintext, row.key_hash) else None


class Operator(models.Model):
    """A console user: one Django user signed in with a session, acting for one tenant.
    The single `ops` role of the roadmap; the API principal stays the Tenant."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="operator"
    )
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="operators")

    class Meta:
        db_table = "operators"

    @classmethod
    def for_user(cls, user: object) -> "Operator | None":
        return (
            cls.objects.select_related("tenant").filter(user_id=getattr(user, "pk", None)).first()
        )


class IdempotencyRecord(models.Model):
    """One row per (tenant, Idempotency-Key). Claimed inside the write's transaction;
    the response is filled in before commit, so a retry sees either nothing or the
    complete stored response, never a half-written one."""

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="+")
    key = models.CharField(max_length=255)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField(null=True)
    response_body = models.TextField(null=True, help_text="rendered JSON, replayed byte for byte")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "idempotency_records"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "key"], name="uq_idempotency_tenant_key")
        ]
        indexes = [models.Index(fields=["created_at"], name="ix_idempotency_created")]


class Plan(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="plans")
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=18, decimal_places=6)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    interval = models.CharField(max_length=8, choices=[(i.value, i.value) for i in Interval])

    class Meta:
        db_table = "plans"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uq_plan_tenant_code")
        ]


class Customer(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="customers")
    name = models.CharField(max_length=200)
    email = models.EmailField()
    stripe_customer_id = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "customers"


class Subscription(models.Model):
    """Billed in advance. Due when `billed_through` is null or in the past; the next
    invoice covers [billed_through or started_at, + plan.interval)."""

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="subscriptions")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="subscriptions")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(
        max_length=16,
        choices=[(s.value, s.value) for s in SubscriptionStatus],
        default=SubscriptionStatus.ACTIVE.value,
    )
    started_at = models.DateTimeField()
    billed_through = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "subscriptions"
        indexes = [models.Index(fields=["status", "billed_through"], name="ix_subs_due")]


class Invoice(models.Model):
    """One billing period of one subscription. Its journal entries are found through the
    journal's own (source_type, source_id) link, so the ledger stays the source of truth."""

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="invoices")
    subscription = models.ForeignKey(
        Subscription, on_delete=models.PROTECT, related_name="invoices"
    )
    description = models.CharField(max_length=200)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    amount = models.DecimalField(max_digits=18, decimal_places=6)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    status = models.CharField(
        max_length=8,
        choices=[(s.value, s.value) for s in InvoiceStatus],
        default=InvoiceStatus.OPEN.value,
    )
    issued_at = models.DateTimeField()
    paid_at = models.DateTimeField(null=True, blank=True)
    stripe_payment_intent_id = models.CharField(max_length=64, null=True, blank=True, unique=True)

    class Meta:
        db_table = "invoices"
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "period_start"], name="uq_invoice_subscription_period"
            )
        ]

    def entry(self, source_type: str) -> "JournalEntry | None":
        """The `invoice` (issue) or `payment` entry posted for this invoice."""
        return JournalEntry.objects.filter(
            tenant_id=self.tenant_id, source_type=source_type, source_id=str(self.id)
        ).first()


class StripeEvent(models.Model):
    """Inbound webhook dedup: one row per Stripe event id. The webhook view inserts and
    returns 200; a Celery task does the work and stamps processed_at."""

    event_id = models.CharField(max_length=64, unique=True)
    type = models.CharField(max_length=64)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "stripe_events"


class WebhookEndpoint(models.Model):
    """A tenant's receiver. The secret signs every delivery; it is returned once on
    creation and stored in the clear because the sender has to use it."""

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="webhook_endpoints")
    url = models.URLField(max_length=500)
    secret = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    disabled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "webhook_endpoints"

    @staticmethod
    def new_secret() -> str:
        return "whsec_" + token_urlsafe(32)


class OutboxMessage(models.Model):
    """One delivery per (event, endpoint), written in the business transaction.

    `next_attempt_at` drives retries; after MAX_ATTEMPTS failures `dead_at` is set and
    the message waits in the dead-letter list until redelivered by hand."""

    MAX_ATTEMPTS = 5

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="+")
    endpoint = models.ForeignKey(WebhookEndpoint, on_delete=models.PROTECT, related_name="outbox")
    event_type = models.CharField(max_length=64)
    payload = models.JSONField(encoder=DjangoJSONEncoder)  # Decimal and datetime become strings
    created_at = models.DateTimeField(auto_now_add=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField()
    delivered_at = models.DateTimeField(null=True, blank=True)
    dead_at = models.DateTimeField(null=True, blank=True)
    last_status = models.PositiveSmallIntegerField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    # W3C trace context of the request that produced the event, so the delivery (picked up
    # by a Beat sweep, not enqueued from the request) joins the same trace.
    traceparent = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        db_table = "webhook_outbox"
        indexes = [
            # Partial: only the rows the 10 s sweep can pick up, not the delivered history.
            models.Index(
                fields=["next_attempt_at"],
                name="ix_outbox_due",
                condition=models.Q(delivered_at__isnull=True, dead_at__isnull=True),
            )
        ]


class Statement(models.Model):
    """A bank or processor statement imported from CSV. Reconciled when every line is
    matched or its exception resolved."""

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="statements")
    source = models.CharField(max_length=16, choices=[("bank", "bank"), ("processor", "processor")])
    period_start = models.DateField()
    period_end = models.DateField()
    uploaded_at = models.DateTimeField(auto_now_add=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "statements"


class StatementLine(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="+")
    statement = models.ForeignKey(Statement, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveIntegerField()
    occurred_on = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=6)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    reference = models.CharField(max_length=128, blank=True, default="")
    description = models.CharField(max_length=200, blank=True, default="")
    matched_entry = models.ForeignKey(
        JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    match_rule = models.CharField(max_length=16, blank=True, default="")

    class Meta:
        db_table = "statement_lines"
        ordering = ["line_no"]
        constraints = [
            models.UniqueConstraint(fields=["statement", "line_no"], name="uq_statement_line_no")
        ]


class ReconciliationException(models.Model):
    """A statement line the rules could not place. Resolved by an adjusting entry
    (posted through the journal, so it balances) or by a recorded explanation."""

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="+")
    statement = models.ForeignKey(Statement, on_delete=models.PROTECT, related_name="exceptions")
    line = models.OneToOneField(StatementLine, on_delete=models.PROTECT, related_name="exception")
    reason = models.CharField(max_length=16)
    difference = models.DecimalField(max_digits=18, decimal_places=6)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    entry = models.ForeignKey(
        JournalEntry,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="the entry whose reference matched with another amount",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution = models.CharField(
        max_length=16,
        blank=True,
        default="",
        choices=[("adjusted", "adjusted"), ("explained", "explained")],
    )
    adjusting_entry = models.OneToOneField(
        JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    explanation = models.TextField(blank=True, default="")

    class Meta:
        db_table = "reconciliation_exceptions"
        ordering = ["id"]


class SettlementMarker(models.Model):
    """A day whose entries are final. The nightly report's sensor waits for this row;
    Beat writes it shortly after midnight, an operator can write it by hand."""

    day = models.DateField(unique=True)
    settled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "settlement_markers"
