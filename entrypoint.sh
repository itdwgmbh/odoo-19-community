#!/bin/bash
set -e

# Read Docker secret from file if _FILE variant is set
file_env() {
    local var="$1"
    local fileVar="${var}_FILE"
    local default="${2:-}"
    local val="$default"

    if [ "${!var:-}" ]; then
        val="${!var}"
    fi

    if [ "${!fileVar:-}" ]; then
        if [ -r "${!fileVar}" ]; then
            val="$(< "${!fileVar}")"
        else
            echo >&2 "Error: Secret file '${!fileVar}' specified by ${fileVar} is not readable"
            exit 1
        fi
    fi

    export "$var"="$val"
    unset "$fileVar"
}

# Database connection defaults
: "${DB_HOST:=db}"
: "${DB_PORT:=5432}"
: "${DB_USER:=odoo}"
: "${DB_PASSWORD:=odoo}"
file_env DB_PASSWORD "$DB_PASSWORD"
file_env ODOO_MASTER_PASSWORD ''

# Initial setup when running as root
if [ "$(id -u)" = "0" ]; then
    echo "Generating odoo.conf from environment variables..."
    python3 /usr/local/bin/generate_odoo_conf.py "$ODOO_RC"

    chown odoo /etc/odoo/odoo.conf
    chown -R odoo /mnt/extra-addons /var/lib/odoo /opt/odoo-customer-addons

    ODOO_HOME=$(getent passwd odoo | cut -d: -f6)
    echo "${DB_HOST}:${DB_PORT}:*:${DB_USER}:${DB_PASSWORD}" > "${ODOO_HOME}/.pgpass"
    chmod 600 "${ODOO_HOME}/.pgpass"
    chown odoo:odoo "${ODOO_HOME}/.pgpass"

    exec gosu odoo "$0" "$@"
fi

DB_ARGS=(
    "--db_host" "$DB_HOST"
    "--db_port" "$DB_PORT"
    "--db_user" "$DB_USER"
    "--db_password" "$DB_PASSWORD"
)

case "$1" in
    -- | odoo)
        shift
        if [[ "$1" == "scaffold" ]]; then
            exec python3 /opt/odoo/src/odoo-bin "$@"
        else
            python3 /usr/local/bin/wait-for-psql.py "${DB_ARGS[@]}" --timeout=60
            exec python3 /opt/odoo/src/odoo-bin "$@" "${DB_ARGS[@]}"
        fi
        ;;
    -*)
        python3 /usr/local/bin/wait-for-psql.py "${DB_ARGS[@]}" --timeout=60
        exec python3 /opt/odoo/src/odoo-bin "$@" "${DB_ARGS[@]}"
        ;;
    *)
        exec "$@"
esac
