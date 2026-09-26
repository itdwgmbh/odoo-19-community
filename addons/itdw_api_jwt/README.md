# JSON-2 JWT authentication

Adds JWTs to Odoo 19's `/json/2/` API. Existing API keys and browser sessions
continue to use Odoo's native bearer authentication. The module does not issue
tokens; an external issuer signs them.

After installation, an Odoo administrator opens **Settings → Technical → JWT
Issuers** and adds each trusted issuer. Set the exact JWT `iss`, the expected
`aud` for this API, the issuer's HTTPS JWKS URL, and the claim containing the
existing Odoo user's login. The default claim is `sub`; choose another claim
when the issuer places the Odoo login elsewhere. No users are created by this
module.

Only RS256 tokens with valid signatures, expiration, issuer, and audience are
accepted. Send them as `Authorization: Bearer <JWT>`, along with Odoo's usual
`X-Odoo-Database` header when database selection requires it. The mapped user
must be active and have the Odoo permissions needed for the requested model method.
