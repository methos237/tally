"""X-Api-Key authentication. The authenticated principal (request.user) is the Tenant."""

from typing import cast

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework import authentication, exceptions
from rest_framework.request import Request

from tally.adapters import rls
from tally.adapters.models import ApiKey, Operator, Tenant

HEADER = "X-Api-Key"


class ApiKeyAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request: Request) -> tuple[Tenant, ApiKey]:
        presented = request.headers.get(HEADER)
        if not presented:
            raise exceptions.NotAuthenticated(f"Missing {HEADER} header")
        key = ApiKey.authenticate(presented)
        if key is None:
            raise exceptions.AuthenticationFailed("Unknown or revoked API key")
        rls.bind(key.tenant_id)  # from here the database shows this tenant's rows only
        return key.tenant, key

    def authenticate_header(self, request: Request) -> str:
        return HEADER


class ConsoleSessionAuthentication(authentication.SessionAuthentication):
    """A signed-in console Operator acts as its tenant. Runs before ApiKeyAuthentication:
    returns None without a session so the key path keeps its 401 wording. CSRF is
    enforced on unsafe methods by the parent class."""

    def authenticate(self, request: Request) -> tuple[Tenant, Operator] | None:
        user = request._request.user
        if not user.is_authenticated:
            return None
        operator = Operator.for_user(user)
        if operator is None:
            return None
        self.enforce_csrf(request)
        rls.bind(operator.tenant_id)
        return operator.tenant, operator

    def authenticate_header(self, request: Request) -> str:
        return HEADER  # the API credential; a browser session is a console convenience


def tenant_of(request: Request) -> Tenant:
    """The authenticated tenant. Views only run after one authentication class succeeded."""
    return cast(Tenant, request.user)


class ApiKeyScheme(OpenApiAuthenticationExtension):  # type: ignore[no-untyped-call]
    """Tells drf-spectacular how X-Api-Key appears in the OpenAPI document."""

    target_class = "tally.api.auth.ApiKeyAuthentication"
    name = "ApiKeyAuth"

    def get_security_definition(self, auto_schema: object) -> dict[str, str]:
        return {"type": "apiKey", "in": "header", "name": HEADER}


class SessionScheme(OpenApiAuthenticationExtension):  # type: ignore[no-untyped-call]
    target_class = "tally.api.auth.ConsoleSessionAuthentication"
    name = "SessionAuth"

    def get_security_definition(self, auto_schema: object) -> dict[str, str]:
        return {"type": "apiKey", "in": "cookie", "name": "sessionid"}
