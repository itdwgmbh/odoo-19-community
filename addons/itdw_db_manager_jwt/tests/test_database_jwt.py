from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from odoo import http, tools
from odoo.addons.itdw_db_manager_jwt import service
from odoo.service import db
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestDatabaseJwt(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def _token(self, **overrides):
        claims = {
            "iss": service.ISSUER,
            "sub": "admin",
            "aud": "odoo.example.test",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        } | overrides
        return jwt.encode(
            claims, self.private_key, algorithm="RS256", headers={"kid": "test"}
        )

    def _patch_auth(self):
        client = patch.object(service, "_jwks_client")
        mocked = client.start()
        self.addCleanup(client.stop)
        mocked.return_value.get_signing_key_from_jwt.return_value = SimpleNamespace(
            key=self.private_key.public_key()
        )
        audience = patch.dict(
            tools.config.options, {"db_manager_jwt_audience": "odoo.example.test"}
        )
        audience.start()
        self.addCleanup(audience.stop)

    def test_replaces_master_password_for_backup(self):
        self._patch_auth()
        with (
            patch.object(http, "db_list", return_value=[self.env.cr.dbname]),
            patch.object(
                db, "dump_db", side_effect=lambda *args: BytesIO(b"backup-bytes")
            ) as dump,
        ):
            response = self.url_open(
                "/web/database/backup",
                data={
                    "name": self.env.cr.dbname,
                    "master_pwd": self._token(),
                    "filestore": "false",
                },
                method="POST",
            )
            self.assertEqual(response.content, b"backup-bytes")
            self.assertEqual(dump.call_count, 1)

            for credential in (
                "static-master-password",
                self._token(sub="nobody"),
                self._token(aud="another.example.test"),
            ):
                with self.subTest(credential=credential[:20]):
                    response = self.url_open(
                        "/web/database/backup",
                        data={"name": self.env.cr.dbname, "master_pwd": credential},
                        method="POST",
                    )
                    self.assertIn(b"Database backup error", response.content)
                    self.assertEqual(dump.call_count, 1)

    def test_authorization_header_and_password_change(self):
        self._patch_auth()
        with (
            patch.object(http, "db_list", return_value=[self.env.cr.dbname]),
            patch.object(
                db, "dump_db", side_effect=lambda *args: BytesIO(b"backup-bytes")
            ),
        ):
            response = self.url_open(
                "/web/database/backup",
                data={"name": self.env.cr.dbname, "filestore": "false"},
                headers={"Authorization": f"Bearer {self._token()}"},
                method="POST",
            )
            self.assertEqual(response.content, b"backup-bytes")
        response = self.url_open(
            "/web/database/change_password",
            data={"master_pwd": self._token(), "master_pwd_new": "new-static-secret"},
            method="POST",
            allow_redirects=False,
        )
        self.assertEqual(response.status_code, 404)

    def test_database_rpc_rejects_static_master_password(self):
        self._patch_auth()
        from odoo.exceptions import AccessDenied

        with self.assertRaises(AccessDenied):
            db.check_super("static-master-password")
        self.assertTrue(db.check_super(self._token()))
        with self.assertRaises(AccessDenied):
            db.check_super(
                self._token(exp=datetime.now(timezone.utc) - timedelta(minutes=1))
            )
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = jwt.encode(
            {
                "iss": service.ISSUER,
                "sub": "admin",
                "aud": "odoo.example.test",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            },
            other_key,
            algorithm="RS256",
            headers={"kid": "test"},
        )
        with self.assertRaises(AccessDenied):
            db.check_super(forged)
        with self.assertRaises(AccessDenied):
            db.dispatch("change_admin_password", [self._token(), "new-static-secret"])
