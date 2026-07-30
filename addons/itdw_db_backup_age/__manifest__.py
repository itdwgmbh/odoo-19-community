# Part of the IT-DW Odoo Community Build. See LICENSE for details.
{
    "name": "Database Backup Encryption (age)",
    "summary": "Encrypts database manager backups with age public-key encryption",
    "description": """
Encrypts backups downloaded from /web/database/backup with age
(https://age-encryption.org) when the ``age_recipients`` option is set in
odoo.conf. Without the option the backup route behaves like stock Odoo.
""",
    "version": "19.0.1.0.0",
    "author": "IT-DW GmbH",
    "website": "https://www.it-dw.com",
    "license": "LGPL-3",
    "category": "Technical",
    "depends": ["web"],
    "installable": True,
}
