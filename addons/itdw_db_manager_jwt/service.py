from functools import lru_cache

import jwt
import odoo
from jwt import PyJWKClient
from odoo.exceptions import AccessDenied
from odoo.service import db

ISSUER = "https://oidc.tailc6b0d.ts.net"
JWKS_URL = f"{ISSUER}/jwks.json"
ADMIN_SUBJECT = "admin"


@lru_cache(maxsize=1)
def _jwks_client():
    return PyJWKClient(JWKS_URL, cache_jwk_set=True, lifespan=300, timeout=5)


def check_super_jwt(token):
    audience = odoo.tools.config.options.get("db_manager_jwt_audience")
    if not audience or not isinstance(token, str):
        raise AccessDenied()
    try:
        key = _jwks_client().get_signing_key_from_jwt(token.strip()).key
        claims = jwt.decode(
            token.strip(),
            key,
            algorithms=["RS256"],
            issuer=ISSUER,
            audience=audience,
            options={"require": ["iss", "sub", "aud", "exp"]},
        )
    except (jwt.PyJWTError, ValueError, TimeoutError, OSError) as exc:
        raise AccessDenied() from exc
    if claims["sub"] != ADMIN_SUBJECT:
        raise AccessDenied()
    return True


_original_dispatch = db.dispatch


def dispatch_jwt(method, params):
    if method == "change_admin_password":
        raise AccessDenied()
    return _original_dispatch(method, params)


db.check_super = check_super_jwt
db.dispatch = dispatch_jwt
