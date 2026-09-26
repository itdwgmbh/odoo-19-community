import re
from functools import lru_cache
from urllib.parse import urlsplit

import jwt
from jwt import PyJWKClient
from odoo import models
from odoo.exceptions import AccessDenied
from odoo.http import request
from odoo.tools.misc import str2bool
from werkzeug.datastructures import WWWAuthenticate
from werkzeug.exceptions import Unauthorized

_BEARER = re.compile(r"^bearer\s+(.+)$", re.IGNORECASE)


@lru_cache(maxsize=16)
def _jwks_client(url):
    return PyJWKClient(url, cache_jwk_set=True, lifespan=300, timeout=5)


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _auth_method_bearer(cls):
        # Native API keys contain only hex characters. A three-part token on
        # JSON-2 is a JWT and must never fall back to another credential type.
        header = request.httprequest.headers.get("Authorization", "")
        match = _BEARER.match(header)
        token = match.group(1) if match else ""
        if not request.httprequest.path.startswith("/json/2/"):
            return super()._auth_method_bearer()
        if token.count(".") != 2:
            jwt_only = (
                request.env["ir.config_parameter"].sudo().get_param("api_jwt.jwt_only")
            )
            if str2bool(jwt_only, False):
                raise Unauthorized(
                    "A JWT is required", www_authenticate=WWWAuthenticate("bearer")
                )
            return super()._auth_method_bearer()

        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
            issuer_name = unverified.get("iss")
            if not isinstance(issuer_name, str):
                raise jwt.InvalidIssuerError("Missing issuer")
            issuers = (
                request.env["api.jwt.issuer"]
                .sudo()
                .search([("issuer", "=", issuer_name), ("active", "=", True)], limit=1)
            )
            if not issuers:
                raise jwt.InvalidIssuerError("Untrusted issuer")
            audience = issuers.audience
            if not audience:
                base_url = (
                    request.env["ir.config_parameter"].sudo().get_param("web.base.url")
                )
                audience = urlsplit(base_url or "").hostname
            if not audience:
                raise jwt.InvalidAudienceError("Odoo hostname is not configured")
            key = _jwks_client(issuers.jwks_url).get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=issuers.issuer,
                audience=audience,
                options={"require": ["exp", "iss", "aud"]},
            )
        except (jwt.PyJWTError, ValueError, TimeoutError, OSError) as exc:
            raise Unauthorized(
                "Invalid JWT", www_authenticate=WWWAuthenticate("bearer")
            ) from exc

        identity = claims.get(issuers.user_claim)
        if not isinstance(identity, str) or not identity:
            raise Unauthorized(
                "JWT user claim is missing", www_authenticate=WWWAuthenticate("bearer")
            )
        users = (
            request.env["res.users"]
            .sudo()
            .search([("login", "=", identity), ("active", "=", True)], limit=1)
        )
        if not users or users.id in cls._get_public_users():
            raise Unauthorized(
                "JWT user is not available", www_authenticate=WWWAuthenticate("bearer")
            )
        if request.env.uid and request.env.uid != users.id:
            raise AccessDenied("Session user does not match the JWT user")

        request.update_env(user=users.id)
        request.session.can_save = False
        cls._auth_method_user()
