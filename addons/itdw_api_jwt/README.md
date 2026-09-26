# JWT API authentication

Accepts JWTs wherever Odoo 19 checks bearer authentication (`/json/2/`,
`/json/1/`, `/doc-bearer/`). Bearer values that are not JWTs (API keys) and
browser sessions continue to use Odoo's native bearer authentication. The
module does not issue tokens; an external issuer signs them.

The deprecated `/jsonrpc`, `/xmlrpc/<service>` and `/xmlrpc/2/<service>`
endpoints return 404 while the module is installed.

After installation, an Odoo administrator opens **Settings → API
Authentication → Manage issuers** and adds each trusted issuer: the exact JWT
`iss`, the issuer's HTTPS JWKS URL, and the claim containing the existing Odoo
user's login (default `sub`). The login must match exactly one active internal
user; portal and public users are rejected. No users are created by this
module.

The JWT `aud` must be the name of the Odoo database. A token is valid only for
the database it names, also when several databases share one host.

Only RS256 tokens with a valid signature, `exp`, `iss`, and `aud` are
accepted; `nbf` is checked when present. The JWT header `kid` selects the
signing key. Send tokens as `Authorization: Bearer <JWT>`, along with Odoo's
usual `X-Odoo-Database` header when database selection requires it. The mapped
user needs the Odoo permissions for the requested model method.

Fetched JWKS are reused for up to 5 minutes. An unknown `kid` or a failed
fetch triggers at most one new fetch per JWKS URL every 30 seconds, so a newly
rotated key is accepted within 30 seconds and a removed key stops working
within 5 minutes.

The bundled **IT-DW GmbH** issuer is active on install; its `sub` claim carries
the Odoo login.

In **Settings → API Authentication**, enable **Require JWTs for bearer routes**
to reject API keys and browser sessions on every bearer route. The switch is
off by default.
