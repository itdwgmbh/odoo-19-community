# Database manager JWT authentication

This server-wide addon replaces the Odoo database manager's master password
with an RS256 JWT from `https://oidc.tailc6b0d.ts.net/jwks.json`. The token
must have `iss=https://oidc.tailc6b0d.ts.net`, `sub=admin`, a valid expiry,
and `aud` equal to `ODOO_DB_MANAGER_JWT_AUDIENCE`. Set that variable to the
canonical Odoo hostname. Without an audience, management requests fail closed.

The issuer grants `sub=admin` only to tailnet nodes with its admin capability.
On such a node, obtain a short-lived token with:

```bash
curl -fsS 'https://oidc.tailc6b0d.ts.net/token?aud=YOUR_ODOO_HOSTNAME&role=admin'
```

Paste the token into the **Admin JWT** field in the database manager. Clients
can instead send `Authorization: Bearer <JWT>` to the manager's POST routes.
Create, duplicate, drop, backup, and restore retain Odoo's existing behavior,
including age-encrypted backup downloads when configured. The master-password
change route is disabled. Legacy database RPC also requires an admin JWT in
its former password argument; changing the master password through RPC is
disabled.

The image loads this addon server-wide by default. It generates an undisclosed
random Odoo master password at startup, so static passwords supplied through
`ODOO_MASTER_PASSWORD` are ignored in this mode. If the server-wide addon is
removed, normal Odoo master-password handling resumes.
