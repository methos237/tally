"""Django models for the ledger. Every table carries tenant_id.

journal_entries and journal_lines are append-only; see migration 0002 for
the triggers that enforce it and the deferred balancing check.
"""

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from tally.domain.journal import AccountType
from tally.domain.money import Currency

CURRENCY_CHOICES = [(c.value, c.value) for c in Currency]


class Tenant(models.Model):
    name = models.CharField(max_length=200, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    rate_limit_per_minute = models.PositiveIntegerField(
        null=True, blank=True, help_text="Overrides RATE_LIMIT_PER_MINUTE for this tenant's keys"
    )

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
    def issue(cls, tenant: Tenant, name: str) -> tuple["ApiKey", str]:
        """Create a key and return (row, plaintext). The plaintext is shown exactly once."""
        from secrets import token_urlsafe

        from django.contrib.auth.hashers import make_password

        secret = token_urlsafe(32)
        plaintext = f"{cls.PREFIX}{secret}"
        row = cls.objects.create(
            tenant=tenant,
            name=name,
            prefix=secret[: cls.PREFIX_LEN],
            key_hash=make_password(plaintext, hasher="argon2"),
        )
        return row, plaintext

    @classmethod
    def authenticate(cls, plaintext: str) -> "ApiKey | None":
        """The live key matching `plaintext`, or None. Constant work for bad prefixes."""
        from django.contrib.auth.hashers import check_password

        if not plaintext.startswith(cls.PREFIX):
            return None
        prefix = plaintext[len(cls.PREFIX) :][: cls.PREFIX_LEN]
        live = cls.objects.filter(prefix=prefix, revoked_at__isnull=True)
        row = live.select_related("tenant").first()
        # ponytail: one Argon2 verify per request; cache verified keys in Redis if p95 matters
        if row is None or not check_password(plaintext, row.key_hash):
            return None
        return row


class IdempotencyRecord(models.Model):
    """One row per (tenant, Idempotency-Key). Claimed inside the write's transaction;
    the response is filled in before commit, so a retry sees either nothing or the
    complete stored response, never a half-written one."""

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="+")
    key = models.CharField(max_length=255)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField(null=True)
    response_body = models.JSONField(null=True, encoder=DjangoJSONEncoder)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "idempotency_records"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "key"], name="uq_idempotency_tenant_key")
        ]
        indexes = [models.Index(fields=["created_at"], name="ix_idempotency_created")]
