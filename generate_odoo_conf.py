#!/usr/bin/env python3
"""Generate odoo.conf from environment variables."""

import os
import sys
from configparser import ConfigParser


def get_env_or_file(var_name, default=""):
    """Get env var, preferring _FILE variant (Docker secrets)."""
    file_path = os.environ.get(f"{var_name}_FILE")
    if file_path:
        try:
            with open(file_path) as f:
                return f.read().rstrip("\n\r")
        except IOError as e:
            print(f"Error: Cannot read secret file '{file_path}': {e}", file=sys.stderr)
            sys.exit(1)
    return os.environ.get(var_name, default)


# (odoo.conf key, env var, default)
OPTIONS = [
    # Database
    ("db_host", "DB_HOST", "db"),
    ("db_port", "DB_PORT", "5432"),
    ("db_user", "DB_USER", "odoo"),
    ("db_name", "ODOO_DB_NAME", ""),
    ("db_template", "ODOO_DB_TEMPLATE", "template1"),
    ("dbfilter", "ODOO_DBFILTER", ".*"),
    ("db_maxconn", "ODOO_DB_MAXCONN", "32"),
    ("db_sslmode", "ODOO_DB_SSLMODE", "prefer"),
    # Paths
    (
        "addons_path",
        "ODOO_ADDONS_PATH",
        "/opt/odoo/src/addons,/mnt/extra-addons,/opt/odoo-customer-addons",
    ),
    ("data_dir", "ODOO_DATA_DIR", "/var/lib/odoo"),
    # Server
    ("proxy_mode", "ODOO_PROXY_MODE", "True"),
    ("workers", "ODOO_WORKERS", "4"),
    ("max_cron_threads", "ODOO_MAX_CRON_THREADS", "2"),
    ("list_db", "ODOO_LIST_DB", "True"),
    ("unaccent", "ODOO_UNACCENT", "True"),
    ("without_demo", "ODOO_WITHOUT_DEMO", "all"),
    # Network
    ("http_interface", "ODOO_HTTP_INTERFACE", "::"),  # :: = dualstack (IPv4+IPv6)
    ("xmlrpc", "ODOO_XMLRPC", "True"),
    ("xmlrpc_port", "ODOO_XMLRPC_PORT", "8069"),
    ("gevent_port", "ODOO_GEVENT_PORT", "8072"),
    # Memory limits
    ("limit_memory_hard", "ODOO_LIMIT_MEMORY_HARD", "4294967296"),
    ("limit_memory_soft", "ODOO_LIMIT_MEMORY_SOFT", "3221225472"),
    ("limit_request", "ODOO_LIMIT_REQUEST", "8192"),
    # Timeouts
    ("limit_time_cpu", "ODOO_LIMIT_TIME_CPU", "600"),
    ("limit_time_real", "ODOO_LIMIT_TIME_REAL", "1200"),
    ("limit_time_real_cron", "ODOO_LIMIT_TIME_REAL_CRON", "3600"),
    # Logging
    ("log_handler", "ODOO_LOG_HANDLER", "['werkzeug:CRITICAL','odoo:WARNING']"),
    ("log_level", "ODOO_LOG_LEVEL", "info"),
    ("log_db", "ODOO_LOG_DB", "False"),
    ("log_db_level", "ODOO_LOG_DB_LEVEL", "warning"),
]

# These use get_env_or_file for Docker secrets support
SECRET_OPTIONS = [
    ("db_password", "DB_PASSWORD", "odoo"),
    ("admin_passwd", "ODOO_MASTER_PASSWORD", ""),
]


def generate_config(output_path="/etc/odoo/odoo.conf"):
    config = ConfigParser()
    config.add_section("options")

    for key, env_var, default in OPTIONS:
        value = os.environ.get(env_var, default)
        if value:
            config.set("options", key, value)

    for key, env_var, default in SECRET_OPTIONS:
        value = get_env_or_file(env_var, default)
        if value:
            config.set("options", key, value)

    try:
        with open(output_path, "w") as f:
            config.write(f)
        print(f"Successfully generated {output_path}")
    except Exception as e:
        print(f"Error generating config file: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    output_path = sys.argv[1] if len(sys.argv) > 1 else "/etc/odoo/odoo.conf"
    generate_config(output_path)
