# JSON-2 JWT authentication

Adds JWTs to Odoo 19's `/json/2/` API. Existing API keys and browser sessions
continue to use Odoo's native bearer authentication. The module does not issue
tokens; an external issuer signs them.

After installation, an Odoo administrator opens **Settings → JSON-2 API →
Manage issuers** and adds each trusted issuer. Set the exact JWT `iss`, the issuer's
HTTPS JWKS URL, and the claim containing the
existing Odoo user's login. The default claim is `sub`; choose another claim
when the issuer places the Odoo login elsewhere. No users are created by this
module.

The bundled **IT-DW GmbH** issuer starts disabled with its issuer and JWKS URL
prefilled. When enabled, its expected `aud` is the hostname of Odoo's canonical
`web.base.url`. Confirm that URL and the claim containing the Odoo login before
enabling it. Other issuers can set an explicit audience to override the Odoo
hostname.

Only RS256 tokens with valid signatures, expiration, issuer, and audience are
accepted. Send them as `Authorization: Bearer <JWT>`, along with Odoo's usual
`X-Odoo-Database` header when database selection requires it. The mapped user
must be active and have the Odoo permissions needed for the requested model method.

In **Settings → JSON-2 API**, enable **Require JWTs for JSON-2** to reject
native API keys and browser sessions on `/json/2/`. The switch is off by
default; other bearer-authenticated routes are unaffected.
