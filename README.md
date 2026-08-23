# Odoo 19 Community Docker Image

Multi-arch (amd64/arm64) Docker image for Odoo 19 Community Edition, built on Debian Trixie. Configuration is driven entirely by environment variables — no manual config file editing needed.

## Quick Start

```bash
docker pull ghcr.io/itdwgmbh/odoo-19-community:latest
```

```bash
docker run -d \
  -p 8069:8069 \
  -e DB_HOST=your-postgres-host \
  -e DB_PASSWORD=your-password \
  ghcr.io/itdwgmbh/odoo-19-community:latest
```

Or use `docker compose up` to start Odoo with PostgreSQL locally.

## Environment Variables

All Odoo configuration is generated at container startup from environment variables.

### Database

| Variable | Default | Description |
|---|---|---|
| `DB_HOST` | `db` | PostgreSQL hostname |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_USER` | `odoo` | Database user |
| `DB_PASSWORD` | `odoo` | Database password |
| `ODOO_DB_NAME` | _(empty)_ | Restrict to a single database |
| `ODOO_DBFILTER` | `.*` | Regex filter for database names |
| `ODOO_DB_MAXCONN` | `32` | Max database connections |
| `ODOO_DB_SSLMODE` | `prefer` | PostgreSQL SSL mode |

### Server

| Variable | Default | Description |
|---|---|---|
| `ODOO_MASTER_PASSWORD` | _(empty)_ | Master password for database management |
| `ODOO_PROXY_MODE` | `True` | Enable when behind a reverse proxy |
| `ODOO_WORKERS` | `4` | Number of worker processes |
| `ODOO_MAX_CRON_THREADS` | `2` | Number of cron worker threads |
| `ODOO_HTTP_INTERFACE` | `::` | Bind address (`::` = IPv4+IPv6 dualstack) |
| `ODOO_HTTP_PORT` | `8069` | HTTP port |
| `ODOO_HTTP_ENABLE` | `True` | Serve HTTP and longpolling |
| `ODOO_GEVENT_PORT` | `8072` | Longpolling/WebSocket port |
| `ODOO_WITHOUT_DEMO` | `all` | Disable demo data |
| `ODOO_LIST_DB` | `True` | Show database selector |
| `ODOO_UNACCENT` | `True` | Enable unaccent for search |

### Memory and Timeouts

| Variable | Default | Description |
|---|---|---|
| `ODOO_LIMIT_MEMORY_HARD` | `4294967296` | Hard memory limit per worker (4 GB) |
| `ODOO_LIMIT_MEMORY_SOFT` | `3221225472` | Soft memory limit per worker (3 GB) |
| `ODOO_LIMIT_REQUEST` | `8192` | Max requests per worker before recycling |
| `ODOO_LIMIT_TIME_CPU` | `600` | CPU time limit per request (seconds) |
| `ODOO_LIMIT_TIME_REAL` | `1200` | Wall time limit per request (seconds) |
| `ODOO_LIMIT_TIME_REAL_CRON` | `3600` | Wall time limit for cron jobs (seconds) |

### Logging

| Variable | Default | Description |
|---|---|---|
| `ODOO_LOG_LEVEL` | `info` | Log level |
| `ODOO_LOG_HANDLER` | `['werkzeug:CRITICAL','odoo:WARNING']` | Log handler configuration |
| `ODOO_LOG_DB` | `False` | Log to database |

### Paths

| Variable | Default | Description |
|---|---|---|
| `ODOO_ADDONS_PATH` | `/opt/odoo/src/addons,/opt/odoo-bundled-addons,/mnt/extra-addons*,/opt/odoo-customer-addons*` | Comma-separated addon paths. A `*` marks an optional mount: Odoo skips it without warning while it holds no addon |
| `ODOO_DATA_DIR` | `/var/lib/odoo` | Odoo data directory |
| `ODOO_SERVER_WIDE_MODULES` | `base,web,itdw_db_backup_age` | Modules loaded server-wide |
| `ODOO_AGE_RECIPIENTS` | (empty) | age public keys for encrypted backups (see `addons/itdw_db_backup_age`) |

## Bundled addons

IT-DW addons shipped in the image under `/opt/odoo-bundled-addons` (see each
addon's README in `addons/`):

| Addon | Purpose |
|---|---|
| `itdw_branding` | IT-DW corporate identity for backend, login, reports and emails |
| `itdw_db_backup_age` | age-encrypted database manager backups (server-wide, config-driven) |
| `ms_graph_base` | Entra ID auth (client secret, certificate, managed or workload identity) + request layer for Microsoft Graph |
| `mail_outbound_msgraph` | Outbound mail via Graph sendMail instead of SMTP |
| `mail_inbound_msgraph` | Read and ingest mailbox messages via Graph (technical) |
| `azure_ai_base` | Azure AI Document Intelligence client (technical) |
| `sepa_xml_base` | Read and create SEPA credit transfer and direct debit XML |
| `invoice_inbound` | Supplier invoice inbox with ZUGFeRD/XRechnung and Azure OCR field extraction |

## Docker Secrets

All password variables support the `_FILE` suffix pattern for Docker secrets:

- `DB_PASSWORD_FILE`
- `ODOO_MASTER_PASSWORD_FILE`
The `_FILE` variant takes precedence over the plain variable.

## Volumes

| Path | Purpose |
|---|---|
| `/etc/odoo` | Generated configuration |
| `/var/lib/odoo` | Filestore, sessions, data |
| `/opt/odoo-customer-addons` | Custom addons |
| `/mnt/extra-addons` | Additional addons |

## Ports

| Port | Purpose |
|---|---|
| `8069` | HTTP |
| `8072` | Longpolling / WebSocket |

## Building

```bash
docker build -t odoo-19 .
```

The image fetches the latest Odoo 19 nightly source during build.

## Tags

- `latest` — most recent build
- `19.0.YYYYMMDD` — pinned to a specific Odoo nightly version
- `sha-<commit>` — pinned to a specific git commit

## Supply chain

Every published image includes:

- **SBOM** — SPDX attestation from BuildKit (Syft), attached to the image
- **Provenance** — SLSA provenance (`mode=max`) for the GitHub Actions build
- **Cosign** — keyless signature via the workflow OIDC identity (Sigstore)
- **Trivy** — post-push scan (`CRITICAL`/`HIGH`, fixed only); SARIF to the repo Security tab

```bash
cosign verify \
  --certificate-identity-regexp 'https://github.com/itdwgmbh/odoo-19-community/.github/workflows/docker-publish.yml@.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/itdwgmbh/odoo-19-community@sha256:<digest>

docker buildx imagetools inspect ghcr.io/itdwgmbh/odoo-19-community:latest \
  --format '{{ json (index .SBOM "linux/amd64").SPDX }}'
```

## License

This project is licensed under the MIT License. Odoo Community Edition is licensed under LGPL-3.0.
