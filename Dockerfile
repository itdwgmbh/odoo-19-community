FROM debian:trixie-slim AS builder

ENV LANG=C.UTF-8
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    libldap2-dev \
    libpq-dev \
    libsasl2-dev \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    python3-dev \
    python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/odoo/src && \
    curl -fsSL https://api.github.com/repos/odoo/odoo/tarball/19.0 | \
    tar -xz --strip-components=1 -C /opt/odoo/src

COPY ./requirements.txt /tmp/
RUN pip3 install --no-cache-dir --break-system-packages \
    --target=/opt/pip-packages -r /tmp/requirements.txt

# Runtime stage
FROM debian:trixie-slim

ARG TARGETARCH
ARG BUILD_DATE
ARG ODOO_VERSION
ARG DEBIAN_FRONTEND=noninteractive

LABEL org.opencontainers.image.title="Odoo 19 Community" \
      org.opencontainers.image.description="Odoo 19 Community Edition" \
      org.opencontainers.image.version="${ODOO_VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.authors="IT-DW GmbH <oss@it-dw.com>" \
      org.opencontainers.image.source="https://github.com/itdwgmbh/odoo-19-community"

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    ODOO_RC=/etc/odoo/odoo.conf \
    PYTHONPATH=/opt/pip-packages:/usr/lib/python3/dist-packages

COPY vendor/wkhtmltox_${TARGETARCH}.deb /tmp/wkhtmltox.deb

# PostgreSQL 18 client from PGDG: trixie ships 17, but pg_dump must be at
# least the server major it dumps from (deployments run PostgreSQL 18).
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg && \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] http://apt.postgresql.org/pub/repos/apt trixie-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 \
    python3-asn1crypto \
    python3-babel \
    python3-bs4 \
    python3-cbor2 \
    python3-cffi \
    python3-chardet \
    python3-cryptography \
    python3-dateutil \
    python3-docutils \
    python3-docx \
    python3-gevent \
    python3-greenlet \
    python3-idna \
    python3-jinja2 \
    python3-jwt \
    python3-ldap \
    python3-libsass \
    python3-magic \
    python3-markupsafe \
    python3-num2words \
    python3-oauthlib \
    python3-openpyxl \
    python3-openssl \
    python3-passlib \
    python3-pdfminer \
    python3-phonenumbers \
    python3-pil \
    python3-polib \
    python3-psutil \
    python3-psycopg2 \
    python3-pypdf \
    python3-qrcode \
    python3-rl-renderpm \
    python3-reportlab \
    python3-requests \
    python3-rjsmin \
    python3-simplejson \
    python3-slugify \
    python3-stdnum \
    python3-tz \
    python3-urllib3 \
    python3-werkzeug \
    python3-zeep \
    python3-xlsxwriter \
    ca-certificates \
    curl \
    fontconfig \
    fonts-dejavu-core \
    gosu \
    postgresql-client-18 \
    tzdata \
    xfonts-75dpi \
    xfonts-base && \
    # wkhtmltopdf (bookworm build — only version compatible with Odoo 19)
    dpkg -i /tmp/wkhtmltox.deb && \
    rm /tmp/wkhtmltox.deb && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN useradd -r -u 999 -d /opt/odoo -s /usr/sbin/nologin odoo && \
    mkdir -p /opt/odoo /etc/odoo /var/lib/odoo /var/lib/odoo/sessions \
             /opt/odoo-customer-addons /mnt/extra-addons && \
    chown -R odoo:odoo /opt/odoo /etc/odoo /var/lib/odoo \
                       /opt/odoo-customer-addons /mnt/extra-addons

COPY --from=builder --chown=odoo:odoo /opt/pip-packages /opt/pip-packages
COPY --from=builder --chown=odoo:odoo /opt/odoo/src /opt/odoo/src

COPY --chmod=755 ./entrypoint.sh /usr/local/bin/entrypoint.sh
COPY --chmod=755 ./wait-for-psql.py /usr/local/bin/wait-for-psql.py
COPY --chmod=755 ./generate_odoo_conf.py /usr/local/bin/generate_odoo_conf.py

WORKDIR /opt/odoo

VOLUME ["/etc/odoo", "/var/lib/odoo", "/opt/odoo-customer-addons", "/mnt/extra-addons"]

EXPOSE 8069 8072

HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -sf http://localhost:8069/web/health || exit 1

ENTRYPOINT ["entrypoint.sh"]
CMD ["odoo"]
