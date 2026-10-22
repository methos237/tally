"""X-Api-Key authentication. The authenticated principal is the tenant."""

from dataclasses import dataclass
from typing import cast

from rest_framework import authentication, exceptions
from rest_framework.request import Request

from tally.adapters.models import ApiKey

HEADER = "X-Api-Key"


@dataclass(frozen=True, slots=True)
class Principal:
    tenant_id: int
    tenant_name: str
    api_key_id: int
    is_authenticated: bool = True


class ApiKeyAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request: Request) -> tuple[Principal, ApiKey]:
        presented = request.headers.get(HEADER)
        if not presented:
            raise exceptions.NotAuthenticated(f"Missing {HEADER} header")
        key = ApiKey.authenticate(presented)
        if key is None:
            raise exceptions.AuthenticationFailed("Unknown or revoked API key")
        return Principal(key.tenant_id, key.tenant.name, key.id), key

    def authenticate_header(self, request: Request) -> str:
        return HEADER


def principal(request: Request) -> Principal:
    """The authenticated tenant. Views only run after ApiKeyAuthentication succeeded."""
    return cast(Principal, request.user)
