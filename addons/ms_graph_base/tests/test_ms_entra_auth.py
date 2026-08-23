import base64
import datetime
import json
import os
import tempfile
from unittest.mock import patch

import jwt
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from odoo.addons.ms_graph_base.models import ms_entra_auth, ms_graph_service
from odoo.tests.common import TransactionCase, tagged

TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT = "66666666-7777-8888-9999-000000000000"
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"


class _Response:
    """Minimal stand-in for requests.Response."""

    def __init__(self, body, status=200):
        self.status_code = status
        self._body = body
        self.content = json.dumps(body).encode()

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def _token_body(token="tok", expires_in=3600, **kw):
    return dict({"access_token": token, "expires_in": expires_in}, **kw)


def _self_signed():
    """Return (private_key, certificate) for the certificate credential."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "odoo-entra-test")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _pem_bundle(key, cert, password=None):
    encryption = (
        serialization.BestAvailableEncryption(password.encode())
        if password
        else serialization.NoEncryption()
    )
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        encryption,
    ) + cert.public_bytes(serialization.Encoding.PEM)


@tagged("post_install", "-at_install")
class TestMsEntraAuth(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.auth = cls.env["ms.entra.auth"]
        cls.key, cls.cert = _self_signed()

    def setUp(self):
        super().setUp()
        ms_entra_auth._token_cache.clear()
        self.addCleanup(ms_entra_auth._token_cache.clear)
        self._configure(tenant_id=TENANT, client_id=CLIENT, client_secret="s3cr3t")

    def _configure(self, **params):
        config = self.env["ir.config_parameter"].sudo()
        for key, value in params.items():
            config.set_param(f"ms_graph.{key}", value)

    def _patch_post(self, *responses):
        queue = iter(responses)
        return patch.object(
            ms_entra_auth.requests, "post", side_effect=lambda *a, **kw: next(queue)
        )

    def _patch_get(self, *responses):
        queue = iter(responses)
        return patch.object(
            ms_entra_auth.requests, "get", side_effect=lambda *a, **kw: next(queue)
        )

    def _no_platform_identity(self):
        """Force the IMDS branch regardless of the host's real environment."""
        return patch.dict(os.environ, {"IDENTITY_ENDPOINT": "", "IDENTITY_HEADER": ""})

    # ------------------------------------------------------------------
    # Client secret
    # ------------------------------------------------------------------
    def test_client_secret_posts_client_credentials_grant(self):
        with self._patch_post(_Response(_token_body())) as post:
            ok, token = self.auth._get_token(GRAPH_SCOPE)
        self.assertTrue(ok)
        self.assertEqual(token, "tok")
        self.assertEqual(post.call_args.args[0], TOKEN_URL)
        self.assertEqual(
            post.call_args.kwargs["data"],
            {
                "grant_type": "client_credentials",
                "scope": GRAPH_SCOPE,
                "client_id": CLIENT,
                "client_secret": "s3cr3t",
            },
        )

    def test_authority_override_targets_national_cloud(self):
        self._configure(authority="https://login.microsoftonline.us/")
        with self._patch_post(_Response(_token_body())) as post:
            self.auth._get_token(GRAPH_SCOPE)
        self.assertEqual(
            post.call_args.args[0],
            f"https://login.microsoftonline.us/{TENANT}/oauth2/v2.0/token",
        )

    def test_auth_headers_wrap_the_token(self):
        with self._patch_post(_Response(_token_body())):
            ok, headers = self.auth._auth_headers(GRAPH_SCOPE)
        self.assertTrue(ok)
        self.assertEqual(headers, {"Authorization": "Bearer tok"})

    # ------------------------------------------------------------------
    # Caching
    # ------------------------------------------------------------------
    def test_token_is_reused_until_expiry(self):
        with self._patch_post(_Response(_token_body())) as post:
            self.auth._get_token(GRAPH_SCOPE)
            ok, token = self.auth._get_token(GRAPH_SCOPE)
        self.assertTrue(ok)
        self.assertEqual(token, "tok")
        self.assertEqual(post.call_count, 1)

    def test_cache_is_keyed_per_scope(self):
        with self._patch_post(
            _Response(_token_body("graph")), _Response(_token_body("vault"))
        ) as post:
            _, graph = self.auth._get_token(GRAPH_SCOPE)
            _, vault = self.auth._get_token("https://vault.azure.net/.default")
        self.assertEqual((graph, vault), ("graph", "vault"))
        self.assertEqual(post.call_count, 2)

    def test_token_shorter_than_the_skew_is_not_reused(self):
        with self._patch_post(
            _Response(_token_body("first", expires_in=100)),
            _Response(_token_body("second")),
        ) as post:
            _, first = self.auth._get_token(GRAPH_SCOPE)
            _, second = self.auth._get_token(GRAPH_SCOPE)
        self.assertEqual((first, second), ("first", "second"))
        self.assertEqual(post.call_count, 2)

    def test_changing_the_identity_bypasses_the_cache(self):
        with self._patch_post(
            _Response(_token_body("old")), _Response(_token_body("new"))
        ) as post:
            self.auth._get_token(GRAPH_SCOPE)
            self._configure(client_id="99999999-0000-0000-0000-000000000000")
            _, token = self.auth._get_token(GRAPH_SCOPE)
        self.assertEqual(token, "new")
        self.assertEqual(post.call_count, 2)

    def test_invalidate_token_drops_one_scope(self):
        with self._patch_post(
            _Response(_token_body("graph")),
            _Response(_token_body("vault")),
            _Response(_token_body("graph2")),
        ) as post:
            self.auth._get_token(GRAPH_SCOPE)
            self.auth._get_token("https://vault.azure.net/.default")
            self.auth._invalidate_token(GRAPH_SCOPE)
            _, graph = self.auth._get_token(GRAPH_SCOPE)
            _, vault = self.auth._get_token("https://vault.azure.net/.default")
        self.assertEqual((graph, vault), ("graph2", "vault"))
        self.assertEqual(post.call_count, 3)

    # ------------------------------------------------------------------
    # Scope / resource forms
    # ------------------------------------------------------------------
    def test_bare_resource_is_normalised_to_a_scope(self):
        with self._patch_post(_Response(_token_body())) as post:
            self.auth._get_token("https://graph.microsoft.com")
        self.assertEqual(post.call_args.kwargs["data"]["scope"], GRAPH_SCOPE)

    def test_both_scope_forms_share_one_cache_entry(self):
        with self._patch_post(_Response(_token_body())) as post:
            self.auth._get_token("https://graph.microsoft.com")
            self.auth._get_token(GRAPH_SCOPE)
        self.assertEqual(post.call_count, 1)

    # ------------------------------------------------------------------
    # Failure paths
    # ------------------------------------------------------------------
    def test_missing_configuration_names_the_keys(self):
        self._configure(client_secret="")
        with self._patch_post() as post:
            ok, error = self.auth._get_token(GRAPH_SCOPE)
        self.assertFalse(ok)
        self.assertIn("ms_graph.client_secret", error)
        post.assert_not_called()

    def test_unknown_auth_mode_is_rejected(self):
        self._configure(auth_mode="password")
        ok, error = self.auth._get_token(GRAPH_SCOPE)
        self.assertFalse(ok)
        self.assertIn("password", error)

    def test_entra_error_description_is_surfaced(self):
        body = {
            "error": "invalid_client",
            "error_description": "AADSTS7000215: Invalid client secret provided.",
        }
        with self._patch_post(_Response(body, status=401)):
            ok, error = self.auth._get_token(GRAPH_SCOPE)
        self.assertFalse(ok)
        self.assertEqual(error, "AADSTS7000215: Invalid client secret provided.")

    def test_failed_acquisition_is_not_cached(self):
        with self._patch_post(
            _Response({"error_description": "boom"}, status=401),
            _Response(_token_body()),
        ) as post:
            ok, _error = self.auth._get_token(GRAPH_SCOPE)
            self.assertFalse(ok)
            ok, token = self.auth._get_token(GRAPH_SCOPE)
        self.assertTrue(ok)
        self.assertEqual(token, "tok")
        self.assertEqual(post.call_count, 2)

    def test_transport_error_is_reported(self):
        with patch.object(
            ms_entra_auth.requests, "post", side_effect=requests.ConnectionError("down")
        ):
            ok, error = self.auth._get_token(GRAPH_SCOPE)
        self.assertFalse(ok)
        self.assertIn("down", error)

    # ------------------------------------------------------------------
    # Certificate
    # ------------------------------------------------------------------
    def _assert_valid_assertion(self, post, expected_password=None):
        data = post.call_args.kwargs["data"]
        self.assertEqual(data["client_assertion_type"], ms_entra_auth.ASSERTION_TYPE)
        self.assertNotIn("client_secret", data)
        assertion = data["client_assertion"]

        headers = jwt.get_unverified_header(assertion)
        expected_x5t = (
            base64.urlsafe_b64encode(self.cert.fingerprint(hashes.SHA1()))
            .rstrip(b"=")
            .decode()
        )
        self.assertEqual(headers["alg"], "RS256")
        self.assertEqual(headers["x5t"], expected_x5t)

        # Signature and claims must verify against the certificate's key.
        claims = jwt.decode(
            assertion,
            self.cert.public_key(),
            algorithms=["RS256"],
            audience=TOKEN_URL,
        )
        self.assertEqual(claims["iss"], CLIENT)
        self.assertEqual(claims["sub"], CLIENT)
        self.assertTrue(claims["jti"])
        self.assertLessEqual(claims["exp"] - claims["iat"], ms_entra_auth.ASSERTION_TTL)
        return claims

    def test_certificate_pem_builds_signed_assertion(self):
        self._configure(
            auth_mode="certificate",
            client_secret="",
            certificate=_pem_bundle(self.key, self.cert).decode(),
        )
        with self._patch_post(_Response(_token_body())) as post:
            ok, token = self.auth._get_token(GRAPH_SCOPE)
        self.assertTrue(ok, token)
        self._assert_valid_assertion(post)

    def test_certificate_accepts_base64_pem(self):
        self._configure(
            auth_mode="certificate",
            certificate=base64.b64encode(_pem_bundle(self.key, self.cert)).decode(),
        )
        with self._patch_post(_Response(_token_body())) as post:
            ok, token = self.auth._get_token(GRAPH_SCOPE)
        self.assertTrue(ok, token)
        self._assert_valid_assertion(post)

    def test_certificate_accepts_base64_pkcs12(self):
        pfx = pkcs12.serialize_key_and_certificates(
            b"odoo",
            self.key,
            self.cert,
            None,
            serialization.BestAvailableEncryption(b"pfxpw"),
        )
        self._configure(
            auth_mode="certificate",
            certificate=base64.b64encode(pfx).decode(),
            certificate_password="pfxpw",
        )
        with self._patch_post(_Response(_token_body())) as post:
            ok, token = self.auth._get_token(GRAPH_SCOPE)
        self.assertTrue(ok, token)
        self._assert_valid_assertion(post)

    def test_certificate_accepts_an_encrypted_pem_key(self):
        self._configure(
            auth_mode="certificate",
            certificate=_pem_bundle(self.key, self.cert, password="pempw").decode(),
            certificate_password="pempw",
        )
        with self._patch_post(_Response(_token_body())) as post:
            ok, token = self.auth._get_token(GRAPH_SCOPE)
        self.assertTrue(ok, token)
        self._assert_valid_assertion(post)

    def test_certificate_path_takes_precedence(self):
        with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as fh:
            fh.write(_pem_bundle(self.key, self.cert))
            path = fh.name
        self.addCleanup(os.unlink, path)
        self._configure(auth_mode="certificate", certificate="", certificate_path=path)
        with self._patch_post(_Response(_token_body())) as post:
            ok, token = self.auth._get_token(GRAPH_SCOPE)
        self.assertTrue(ok, token)
        self._assert_valid_assertion(post)

    def test_certificate_without_a_certificate_block_is_rejected(self):
        key_only = self.key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        self._configure(auth_mode="certificate", certificate=key_only.decode())
        with self._patch_post() as post:
            ok, error = self.auth._get_token(GRAPH_SCOPE)
        self.assertFalse(ok)
        self.assertIn("certificate", error.lower())
        post.assert_not_called()

    def test_certificate_wrong_password_is_reported(self):
        self._configure(
            auth_mode="certificate",
            certificate=_pem_bundle(self.key, self.cert, password="right").decode(),
            certificate_password="wrong",
        )
        with self._patch_post() as post:
            ok, error = self.auth._get_token(GRAPH_SCOPE)
        self.assertFalse(ok)
        self.assertIn("Cannot load Entra certificate", error)
        post.assert_not_called()

    def test_certificate_mode_requires_certificate_material(self):
        self._configure(auth_mode="certificate", certificate="", certificate_path="")
        ok, error = self.auth._get_token(GRAPH_SCOPE)
        self.assertFalse(ok)
        self.assertIn("ms_graph.certificate", error)

    # ------------------------------------------------------------------
    # Managed identity
    # ------------------------------------------------------------------
    def test_system_assigned_identity_queries_imds(self):
        self._configure(auth_mode="managed_identity")
        with (
            self._no_platform_identity(),
            self._patch_get(_Response(_token_body(expires_in="3599"))) as get,
        ):
            ok, token = self.auth._get_token(GRAPH_SCOPE)
        self.assertTrue(ok, token)
        self.assertEqual(token, "tok")
        self.assertEqual(get.call_args.args[0], ms_entra_auth.IMDS_URL)
        self.assertEqual(get.call_args.kwargs["headers"], {"Metadata": "true"})
        self.assertEqual(
            get.call_args.kwargs["params"],
            {
                "resource": "https://graph.microsoft.com",
                "api-version": ms_entra_auth.IMDS_API_VERSION,
            },
        )

    def test_managed_identity_needs_no_app_registration(self):
        self._configure(
            auth_mode="managed_identity", tenant_id="", client_id="", client_secret=""
        )
        with self._no_platform_identity(), self._patch_get(_Response(_token_body())):
            ok, token = self.auth._get_token(GRAPH_SCOPE)
        self.assertTrue(ok, token)

    def test_user_assigned_identity_passes_its_client_id(self):
        self._configure(
            auth_mode="managed_identity",
            managed_identity_client_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
        with (
            self._no_platform_identity(),
            self._patch_get(_Response(_token_body())) as get,
        ):
            self.auth._get_token(GRAPH_SCOPE)
        self.assertEqual(
            get.call_args.kwargs["params"]["client_id"],
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )

    def test_platform_identity_endpoint_is_preferred(self):
        self._configure(auth_mode="managed_identity")
        env = {
            "IDENTITY_ENDPOINT": "http://127.0.0.1:42356/msi/token",
            "IDENTITY_HEADER": "header-secret",
        }
        with (
            patch.dict(os.environ, env),
            self._patch_get(_Response(_token_body())) as get,
        ):
            ok, token = self.auth._get_token(GRAPH_SCOPE)
        self.assertTrue(ok, token)
        self.assertEqual(get.call_args.args[0], env["IDENTITY_ENDPOINT"])
        self.assertEqual(
            get.call_args.kwargs["headers"], {"X-IDENTITY-HEADER": "header-secret"}
        )
        self.assertEqual(
            get.call_args.kwargs["params"]["api-version"],
            ms_entra_auth.IDENTITY_API_VERSION,
        )

    def test_imds_expires_on_is_used_when_expires_in_is_absent(self):
        self._configure(auth_mode="managed_identity")
        soon = int(datetime.datetime.now(datetime.UTC).timestamp()) + 130
        body = {"access_token": "tok", "expires_on": str(soon)}
        with (
            self._no_platform_identity(),
            self._patch_get(_Response(body), _Response(_token_body("second"))) as get,
        ):
            _, first = self.auth._get_token(GRAPH_SCOPE)
            _, second = self.auth._get_token(GRAPH_SCOPE)
        # 130s minus the 120s skew leaves ~10s of usable cache life.
        self.assertEqual(first, "tok")
        self.assertEqual(second, "tok")
        self.assertEqual(get.call_count, 1)

    def test_imds_error_is_surfaced(self):
        self._configure(auth_mode="managed_identity")
        body = {"error": "invalid_request", "error_description": "Identity not found"}
        with self._no_platform_identity(), self._patch_get(_Response(body, status=400)):
            ok, error = self.auth._get_token(GRAPH_SCOPE)
        self.assertFalse(ok)
        self.assertEqual(error, "Identity not found")

    # ------------------------------------------------------------------
    # Workload identity (AKS)
    # ------------------------------------------------------------------
    def _projected_token(self, content="projected.sa.token"):
        """Write a federated token file the way the AKS webhook projects one."""
        with tempfile.NamedTemporaryFile("w", suffix=".jwt", delete=False) as fh:
            fh.write(content)
            path = fh.name
        self.addCleanup(os.unlink, path)
        return path

    def _aks_env(self, path, **overrides):
        env = {
            "AZURE_TENANT_ID": TENANT,
            "AZURE_CLIENT_ID": CLIENT,
            "AZURE_FEDERATED_TOKEN_FILE": path,
            "AZURE_AUTHORITY_HOST": "https://login.microsoftonline.com/",
        }
        env.update(overrides)
        return patch.dict(os.environ, env)

    def test_workload_identity_posts_the_projected_token(self):
        path = self._projected_token()
        self._configure(
            auth_mode="workload_identity", tenant_id="", client_id="", client_secret=""
        )
        with self._aks_env(path), self._patch_post(_Response(_token_body())) as post:
            ok, token = self.auth._get_token(GRAPH_SCOPE)
        self.assertTrue(ok, token)
        self.assertEqual(token, "tok")
        self.assertEqual(post.call_args.args[0], TOKEN_URL)
        self.assertEqual(
            post.call_args.kwargs["data"],
            {
                "grant_type": "client_credentials",
                "scope": GRAPH_SCOPE,
                "client_id": CLIENT,
                "client_assertion_type": ms_entra_auth.ASSERTION_TYPE,
                "client_assertion": "projected.sa.token",
            },
        )

    def test_workload_identity_rereads_the_rotated_token(self):
        path = self._projected_token("first.token")
        self._configure(auth_mode="workload_identity", tenant_id="", client_id="")
        with (
            self._aks_env(path),
            self._patch_post(
                _Response(_token_body("a")), _Response(_token_body("b"))
            ) as post,
        ):
            self.auth._get_token(GRAPH_SCOPE)
            with open(path, "w") as fh:
                fh.write("rotated.token")
            self.auth._invalidate_token(GRAPH_SCOPE)
            self.auth._get_token(GRAPH_SCOPE)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(
            post.call_args.kwargs["data"]["client_assertion"], "rotated.token"
        )

    def test_workload_identity_config_overrides_the_injected_environment(self):
        path = self._projected_token()
        other = self._projected_token("other.token")
        self._configure(
            auth_mode="workload_identity",
            tenant_id="99999999-9999-9999-9999-999999999999",
            federated_token_file=other,
        )
        with self._aks_env(path), self._patch_post(_Response(_token_body())) as post:
            ok, token = self.auth._get_token(GRAPH_SCOPE)
        self.assertTrue(ok, token)
        self.assertEqual(
            post.call_args.args[0],
            "https://login.microsoftonline.com/"
            "99999999-9999-9999-9999-999999999999/oauth2/v2.0/token",
        )
        self.assertEqual(
            post.call_args.kwargs["data"]["client_assertion"], "other.token"
        )

    def test_workload_identity_honours_the_authority_host(self):
        path = self._projected_token()
        self._configure(auth_mode="workload_identity", tenant_id="", client_id="")
        env = self._aks_env(
            path, AZURE_AUTHORITY_HOST="https://login.microsoftonline.us"
        )
        with env, self._patch_post(_Response(_token_body())) as post:
            self.auth._get_token(GRAPH_SCOPE)
        self.assertEqual(
            post.call_args.args[0],
            f"https://login.microsoftonline.us/{TENANT}/oauth2/v2.0/token",
        )

    def test_workload_identity_without_the_environment_is_rejected(self):
        self._configure(auth_mode="workload_identity", tenant_id="", client_id="")
        env = patch.dict(
            os.environ,
            {
                "AZURE_TENANT_ID": "",
                "AZURE_CLIENT_ID": "",
                "AZURE_FEDERATED_TOKEN_FILE": "",
            },
        )
        with env, self._patch_post() as post:
            ok, error = self.auth._get_token(GRAPH_SCOPE)
        self.assertFalse(ok)
        self.assertIn("AZURE_FEDERATED_TOKEN_FILE", error)
        self.assertIn("ms_graph.tenant_id", error)
        post.assert_not_called()

    def test_workload_identity_missing_token_file_is_reported(self):
        self._configure(auth_mode="workload_identity", tenant_id="", client_id="")
        with (
            self._aks_env("/nonexistent/azure-identity-token"),
            self._patch_post() as post,
        ):
            ok, error = self.auth._get_token(GRAPH_SCOPE)
        self.assertFalse(ok)
        self.assertIn("Cannot read federated token", error)
        post.assert_not_called()

    def test_workload_identity_empty_token_file_is_reported(self):
        path = self._projected_token("   ")
        self._configure(auth_mode="workload_identity", tenant_id="", client_id="")
        with self._aks_env(path), self._patch_post() as post:
            ok, error = self.auth._get_token(GRAPH_SCOPE)
        self.assertFalse(ok)
        self.assertIn("is empty", error)
        post.assert_not_called()


@tagged("post_install", "-at_install")
class TestMsGraphServiceAuth(TransactionCase):
    """The Graph client must take its Authorization header from ms.entra.auth."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env["ms.graph.service"]

    def setUp(self):
        super().setUp()
        ms_entra_auth._token_cache.clear()
        self.addCleanup(ms_entra_auth._token_cache.clear)

    def test_graph_request_sends_the_entra_token(self):
        config = self.env["ir.config_parameter"].sudo()
        config.set_param("ms_graph.tenant_id", TENANT)
        config.set_param("ms_graph.client_id", CLIENT)
        config.set_param("ms_graph.client_secret", "s3cr3t")

        with (
            patch.object(
                ms_entra_auth.requests, "post", return_value=_Response(_token_body())
            ),
            patch.object(
                ms_graph_service.requests,
                "request",
                return_value=_Response({"id": "1"}),
            ) as request,
        ):
            ok, body = self.service._graph_request("GET", "/me")

        self.assertTrue(ok, body)
        self.assertEqual(body, {"id": "1"})
        headers = request.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer tok")
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_graph_request_reports_the_auth_failure(self):
        config = self.env["ir.config_parameter"].sudo()
        config.set_param("ms_graph.tenant_id", "")
        config.set_param("ms_graph.client_id", "")
        config.set_param("ms_graph.client_secret", "")

        ok, error = self.service._graph_request("GET", "/me")
        self.assertFalse(ok)
        self.assertIn("not configured", error)
