# Odoo 19 Community Docker Image

Multi-arch Docker image for Odoo 19 Community Edition with IT-DW addons. `odoo.conf` is generated at container start from environment variables.

## Quick Start

```bash
docker run -d \
  -p 8069:8069 \
  -e DB_HOST=your-postgres-host \
  -e DB_PASSWORD=your-password \
  ghcr.io/itdwgmbh/odoo-19-community:latest
```

`docker compose up` starts Odoo with PostgreSQL locally.

Tags: `latest`, the Odoo nightly version, and `sha-<commit>`.

## Configuration

`generate_odoo_conf.py` maps each environment variable to its `odoo.conf` key and default. `DB_PASSWORD` accepts a `_FILE` variant for Docker secrets, which takes precedence. Set `ODOO_DB_MANAGER_JWT_AUDIENCE` to the canonical Odoo hostname to enable JWT-protected database management; see the database manager JWT addon README. With that server-wide addon loaded, `ODOO_MASTER_PASSWORD` is ignored.

A `*` after an `ODOO_ADDONS_PATH` entry marks an optional mount: Odoo skips it without warning while it holds no addon.

The IT-DW addons are bundled under `/opt/odoo-bundled-addons`; each has a README under `addons/`.

## Supply chain

Published images carry an SBOM and SLSA provenance attestation, a keyless cosign signature, and a Trivy scan in the repo Security tab.

```bash
cosign verify \
  --certificate-identity-regexp 'https://github.com/itdwgmbh/odoo-19-community/.github/workflows/docker-publish.yml@.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/itdwgmbh/odoo-19-community@sha256:<digest>

docker buildx imagetools inspect ghcr.io/itdwgmbh/odoo-19-community:latest \
  --format '{{ json (index .SBOM "linux/amd64").SPDX }}'
```

## License

MIT. Odoo Community Edition is licensed under LGPL-3.0.
