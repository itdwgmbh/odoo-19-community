import hashlib
import hmac
import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from odoo.tests import HttpCase, new_test_user, tagged


class _JwksHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.hits += 1
        body = json.dumps(self.server.jwks).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@tagged("post_install", "-at_install")
class TestJwtAuthentication(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(
            cls.private_key.public_key(), as_dict=True
        )
        cls.jwks_server = ThreadingHTTPServer(("127.0.0.1", 0), _JwksHandler)
        cls.jwks_server.hits = 0
        cls.jwks_server.jwks = {"keys": [jwk | {"kid": "test", "use": "sig"}]}
        threading.Thread(target=cls.jwks_server.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.jwks_server.server_close)
        cls.addClassCleanup(cls.jwks_server.shutdown)

        cls.user = new_test_user(cls.env, "jwt-user")
        cls.issuer = cls.env["api.jwt.issuer"].create(
            {
                "name": "Test issuer",
                "issuer": "https://identity.example.test/",
                "jwks_url": "https://identity.example.test/keys",
                "user_claim": "account",
            }
        )
        # The model only accepts HTTPS URLs; the test server speaks plain HTTP.
        # A unique path per run keeps the process-wide JWKS cache isolated.
        cls.env.cr.execute(
            "UPDATE api_jwt_issuer SET jwks_url = %s WHERE id = %s",
            [
                f"http://127.0.0.1:{cls.jwks_server.server_port}/{uuid.uuid4().hex}",
                cls.issuer.id,
            ],
        )
        cls.issuer.invalidate_recordset()

    def _claims(self, **overrides):
        claims = {
            "iss": self.issuer.issuer,
            "aud": self.env.cr.dbname,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "account": self.user.login,
        } | overrides
        return {name: value for name, value in claims.items() if value is not None}

    def _token(self, key=None, algorithm="RS256", kid="test", **overrides):
        claims = self._claims(**overrides)
        key = self.private_key if key is None else key
        return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": kid})

    def _hs256(self, secret):
        # PyJWT refuses to sign HS256 with an RSA public key, so the token is built by hand.
        token = jwt.encode(
            self._claims(), "unused", algorithm="HS256", headers={"kid": "test"}
        )
        signing_input = token.rsplit(".", 1)[0]
        signature = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
        return f"{signing_input}.{jwt.utils.base64url_encode(signature).decode()}"

    def _call(self, token=None, headers=None):
        headers = {
            "Content-Type": "application/json",
            "X-Odoo-Database": self.env.cr.dbname,
        } | (headers or {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return self.url_open(
            "/json/2/res.users/search",
            data=json.dumps({"domain": [["id", "=", self.user.id]]}),
            headers=headers,
        )

    def _api_key(self):
        # sudo skips the user-level expiry check, which compares a UTC value
        # against the server's local time.
        return (
            self.user.with_user(self.user)
            .env["res.users.apikeys"]
            .sudo()
            ._generate(
                scope="rpc",
                name="test",
                expiration_date=datetime.now(UTC).replace(tzinfo=None)
                + timedelta(minutes=5),
            )
        )

    def test_accepts_token_for_database_audience(self):
        response = self._call(self._token())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [self.user.id])

    def test_rejects_invalid_tokens(self):
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_pem = self.private_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        portal = new_test_user(self.env, "jwt-portal", groups="base.group_portal")
        inactive = new_test_user(self.env, "jwt-inactive")
        inactive.active = False
        tokens = {
            "wrong signature": self._token(key=other_key),
            "other audience": self._token(aud="other-database"),
            "expired": self._token(exp=datetime.now(UTC) - timedelta(minutes=1)),
            "no expiry": self._token(exp=None),
            "untrusted issuer": self._token(iss="https://untrusted.example.test/"),
            "unsigned": self._token(key="", algorithm="none"),
            "HS256 with public key": self._hs256(public_pem),
            "unknown login": self._token(account="no-such-user"),
            "portal user": self._token(account=portal.login),
            "inactive user": self._token(account=inactive.login),
        }
        for case, token in tokens.items():
            with self.subTest(case):
                response = self._call(token)
                self.assertEqual(response.status_code, 401, response.text)

    def test_unknown_kids_do_not_force_jwks_fetches(self):
        self.assertEqual(self._call(self._token()).status_code, 200)
        hits = self.jwks_server.hits
        for _ in range(3):
            response = self._call(self._token(kid=uuid.uuid4().hex))
            self.assertEqual(response.status_code, 401, response.text)
        self.assertLessEqual(self.jwks_server.hits - hits, 1)

    def test_rejects_token_for_other_session_user(self):
        self.authenticate("admin", "admin")
        response = self._call(self._token())
        self.assertEqual(response.status_code, 403, response.text)

    def test_jwt_only_rejects_api_keys_and_sessions(self):
        session_headers = {
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
        }
        key = self._api_key()
        self.assertEqual(self._call(key).status_code, 200)
        self.authenticate(self.user.login, self.user.login)
        self.assertEqual(self._call(headers=session_headers).status_code, 200)

        self.env["ir.config_parameter"].sudo().set_param("api_jwt.jwt_only", True)
        self.assertEqual(self._call(key).status_code, 401)
        self.assertEqual(self._call(headers=session_headers).status_code, 401)
        self.assertEqual(self._call(self._token()).status_code, 200)

    def test_deprecated_rpc_endpoints_are_disabled(self):
        response = self.url_open(
            "/jsonrpc",
            data=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {"service": "common", "method": "version", "args": []},
                }
            ),
            headers={
                "Content-Type": "application/json",
                "X-Odoo-Database": self.env.cr.dbname,
            },
        )
        self.assertEqual(response.json()["error"]["code"], 404, response.text)
        body = "<?xml version='1.0'?><methodCall><methodName>version</methodName></methodCall>"
        for path in ("/xmlrpc/common", "/xmlrpc/2/common"):
            with self.subTest(path):
                response = self.url_open(
                    path,
                    data=body,
                    headers={
                        "Content-Type": "text/xml",
                        "X-Odoo-Database": self.env.cr.dbname,
                    },
                )
                self.assertEqual(response.status_code, 404, response.text)
