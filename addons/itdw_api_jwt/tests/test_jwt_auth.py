from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from odoo.addons.itdw_api_jwt.models import ir_http
from odoo.tests import HttpCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestJwtAuthentication(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, "jwt-test-user")
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwks_url = "https://identity.example.test/keys"
        cls.issuer = cls.env["api.jwt.issuer"].create(
            {
                "name": "Test issuer",
                "issuer": "https://identity.example.test/",
                "audience": "odoo-api",
                "jwks_url": cls.jwks_url,
                "user_claim": "account",
            }
        )

    def _token(self, **overrides):
        claims = {
            "iss": self.issuer.issuer,
            "aud": self.issuer.audience,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            "account": self.user.login,
        } | overrides
        return jwt.encode(
            claims, self.private_key, algorithm="RS256", headers={"kid": "test"}
        )

    def _call(self, token):
        with patch.object(ir_http, "_jwks_client") as client:
            client.return_value.get_signing_key_from_jwt.return_value = SimpleNamespace(
                key=self.private_key.public_key()
            )
            response = self.url_open(
                "/json/2/res.users/search",
                data=f'{{"domain": [["id", "=", {self.user.id}]]}}',
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "X-Odoo-Database": self.env.cr.dbname,
                },
            )
            if client.called:
                client.assert_called_with(self.jwks_url)
            return response

    def test_accepts_configured_claim_from_verified_issuer(self):
        response = self._call(self._token())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [self.user.id])

    def test_rejects_wrong_signature_audience_and_expiry(self):
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        bad_signature = jwt.encode(
            {
                "iss": self.issuer.issuer,
                "aud": self.issuer.audience,
                "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
                "account": self.user.login,
            },
            other_key,
            algorithm="RS256",
            headers={"kid": "test"},
        )
        for token in (
            bad_signature,
            self._token(aud="another-api"),
            self._token(exp=datetime.now(timezone.utc) - timedelta(minutes=1)),
            self._token(account="no-such-odoo-user"),
            self._token(iss="https://untrusted.example.test/"),
        ):
            with self.subTest(token=token[:20]):
                response = self._call(token)
                self.assertEqual(response.status_code, 401, response.text)

    def test_issuer_uses_its_own_claim(self):
        second = self.env["api.jwt.issuer"].create(
            {
                "name": "Other issuer",
                "issuer": "https://other.example.test/",
                "audience": "odoo-api",
                "jwks_url": self.jwks_url,
                "user_claim": "sub",
            }
        )
        response = self._call(
            self._token(iss=second.issuer, sub=self.user.login, account="wrong")
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_native_api_key_still_works(self):
        key = (
            self.user.with_user(self.user)
            .env["res.users.apikeys"]
            ._generate(
                scope="rpc",
                name="test",
                expiration_date=datetime.now(timezone.utc).replace(tzinfo=None)
                + timedelta(minutes=5),
            )
        )
        response = self._call(key)
        self.assertEqual(response.status_code, 200, response.text)
