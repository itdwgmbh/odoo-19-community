{
    "name": "Database Manager JWT Authentication",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "summary": "Use an admin JWT instead of Odoo's master password for database operations",
    "author": "IT-DW GmbH",
    "license": "LGPL-3",
    "depends": ["itdw_db_backup_age"],
    "external_dependencies": {"python": ["jwt", "cryptography"]},
    "installable": True,
    "application": False,
}
