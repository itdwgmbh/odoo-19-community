import re
import time
from functools import lru_cache

import jwt
import requests
from odoo import models
from odoo.exceptions import AccessDenied
from odoo.http import request
from odoo.tools.misc import str2bool
from werkzeug.datastructures import WWWAuthenticate
from werkzeug.exceptions import Unauthorized

_BEARER = re.compile(r"^bearer\s+(.+)$", re.IGNORECASE)
_JWKS_MAX_AGE = 300  # seconds a fetched key set is used before it is fetched again
_JWKS_MIN_INTERVAL = 30  # minimum seconds between two fetches of one JWKS URL
_JWKS_TIMEOUT = 5


def _unauthorized(message):
    return Unauthorized(message, www_authenticate=WWWAuthenticate("bearer"))


class _Jwks:
    """Signing keys of one JWKS URL.

    Unknown ``kid`` values and failed fetches trigger at most one fetch per
    ``_JWKS_MIN_INTERVAL``, so unauthenticated requests cannot force a fetch
    per request.
    """

    def __init__(self, url):
        self.url = url
        self.keys = {}
        self.fetched_at = self.attempted_at = float("-inf")

    def signing_key(self, kid):
        if not isinstance(kid, str):
            raise jwt.PyJWKClientError("JWT header has no kid")
        now = time.monotonic()
        stale = now - self.fetched_at > _JWKS_MAX_AGE
        if (
            stale or kid not in self.keys
        ) and now - self.attempted_at > _JWKS_MIN_INTERVAL:
            self.attempted_at = now
            try:
                self.keys = self._fetch()
            except Exception:
                self.keys = {}
                raise
            self.fetched_at = now
        if kid not in self.keys:
            raise jwt.PyJWKClientError(f"No signing key for kid {kid!r}")
        return self.keys[kid].key

    def _fetch(self):
        response = requests.get(self.url, timeout=_JWKS_TIMEOUT, allow_redirects=False)
        if response.status_code != 200:
            raise requests.HTTPError(f"JWKS returned HTTP {response.status_code}")
        data = response.json()
        if not isinstance(data, dict):
            raise jwt.PyJWKSetError("JWKS is not a JSON object")
        return {
            key.key_id: key
            for key in jwt.PyJWKSet.from_dict(data).keys
            if key.key_id and key.public_key_use in ("sig", None)
        }


@lru_cache(maxsize=16)
def _jwks(url):
    return _Jwks(url)


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _auth_method_bearer(cls):
        # Native API keys are hex; a three-part token is a JWT and never
        # falls back to API key authentication.
        match = _BEARER.match(request.httprequest.headers.get("Authorization", ""))
        token = match.group(1) if match else ""
        if token.count(".") != 2:
            jwt_only = (
                request.env["ir.config_parameter"].sudo().get_param("api_jwt.jwt_only")
            )
            if str2bool(jwt_only, False):
                raise _unauthorized("A JWT is required")
            return super()._auth_method_bearer()

        uid = cls._jwt_uid(token)
        if request.env.uid and request.env.uid != uid:
            raise AccessDenied("Session user does not match the JWT user")
        request.update_env(user=uid)
        request.session.can_save = False
        cls._auth_method_user()

    @classmethod
    def _jwt_uid(cls, token):
        """Verify ``token`` and return the id of the active internal user it names.

        The expected audience is the name of the current database.
        """
        env = request.env(su=True)
        Issuer = env["api.jwt.issuer"]
        try:
            iss = jwt.decode(token, options={"verify_signature": False}).get("iss")
            issuer = Issuer
            if isinstance(iss, str):
                issuer = Issuer.search([("issuer", "=", iss)])
            if not issuer:
                raise jwt.InvalidIssuerError("Untrusted issuer")
            kid = jwt.get_unverified_header(token).get("kid")
            claims = jwt.decode(
                token,
                _jwks(issuer.jwks_url).signing_key(kid),
                algorithms=["RS256"],
                issuer=issuer.issuer,
                audience=env.cr.dbname,
                options={"require": ["exp", "iss", "aud"]},
            )
        except (jwt.PyJWTError, requests.RequestException, ValueError) as exc:
            raise _unauthorized("Invalid JWT") from exc

        login = claims.get(issuer.user_claim)
        users = env["res.users"]
        if isinstance(login, str) and login:
            users = users.search(
                [("login", "=", login), ("share", "=", False)], limit=2
            )
        if len(users) != 1:
            raise _unauthorized("JWT user is not available")
        return users.id
