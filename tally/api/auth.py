"""X-Api-Key authentication. The authenticated principal (request.user) is the Tenant."""

from typing import cast

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework import authentication, exceptions
from rest_framework.request import Request

from tally.adapters.models import ApiKey, Tenant

HEADER = "X-Api-Key"


class ApiKeyAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request: Request) -> tuple[Tenant, ApiKey]:
        presented = request.headers.get(HEADER)
        if not presented:
            raise exceptions.NotAuthenticated(f"Missing {HEADER} header")
        key = ApiKey.authenticate(presented)
        if key is None:
            raise exceptions.AuthenticationFailed("Unknown or revoked API key")
        return key.tenant, key

    def authenticate_header(self, request: Request) -> str:
        return HEADER


def tenant_of(request: Request) -> Tenant:
    """The authenticated tenant. Views only run after ApiKeyAuthentication succeeded."""
    return cast(Tenant, request.user)


class ApiKeyScheme(OpenApiAuthenticationExtension):  # type: ignore[no-untyped-call]
    """Tells drf-spectacular how X-Api-Key appears in the OpenAPI document."""

    target_class = "tally.api.auth.ApiKeyAuthentication"
    name = "ApiKeyAuth"

    def get_security_definition(self, auto_schema: object) -> dict[str, str]:
        return {"type": "apiKey", "in": "header", "name": HEADER}
