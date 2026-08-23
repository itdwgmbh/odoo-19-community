#!/usr/bin/env python3
"""Wait for PostgreSQL database to become available."""

import argparse
import os
import sys
import time

import psycopg2


def wait_for_postgres(host, port, user, password, timeout, sslmode="prefer"):
    """Wait for PostgreSQL to become available with exponential backoff."""
    start_time = time.time()
    attempt = 0
    max_sleep = 10  # Cap backoff at 10 seconds

    while True:
        elapsed = time.time() - start_time
        if elapsed >= timeout:
            print(f"Database connection failed after {timeout}s", file=sys.stderr)
            return False

        try:
            conn = psycopg2.connect(
                user=user,
                host=host,
                port=port,
                password=password,
                dbname="postgres",
                sslmode=sslmode,
                connect_timeout=5,
            )
            conn.close()
            print(f"Database is ready! (connected after {elapsed:.1f}s)")
            return True
        except psycopg2.OperationalError as e:
            attempt += 1
            # Exponential backoff: 1s, 2s, 4s, 8s, 10s, 10s...
            sleep_time = min(2 ** (attempt - 1), max_sleep)
            remaining = timeout - elapsed

            if remaining <= 0:
                print(f"Database connection failed: {e}", file=sys.stderr)
                return False

            print(
                f"Waiting for database... ({elapsed:.0f}s elapsed, attempt {attempt})"
            )
            time.sleep(min(sleep_time, remaining))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wait for PostgreSQL to be ready")
    parser.add_argument("--db_host", required=True, help="Database host")
    parser.add_argument("--db_port", required=True, help="Database port")
    parser.add_argument("--db_user", required=True, help="Database user")
    parser.add_argument(
        "--db_password",
        default=None,
        help="Database password (prefer DB_PASSWORD env var)",
    )
    parser.add_argument(
        "--db_sslmode",
        default="prefer",
        help="SSL mode (disable, allow, prefer, require)",
    )
    parser.add_argument(
        "--timeout", type=int, default=60, help="Connection timeout in seconds"
    )

    args = parser.parse_args()

    # Prefer environment variable for password (more secure than CLI arg)
    password = args.db_password or os.environ.get("DB_PASSWORD", "")

    success = wait_for_postgres(
        host=args.db_host,
        port=args.db_port,
        user=args.db_user,
        password=password,
        timeout=args.timeout,
        sslmode=args.db_sslmode,
    )

    sys.exit(0 if success else 1)
