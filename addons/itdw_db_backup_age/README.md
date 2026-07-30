# Database Backup Encryption (age)

Encrypts backups downloaded from `/web/database/backup` with
[age](https://age-encryption.org). Bundled in the IT-DW community image and
loaded server-wide; no installation into a database is required.

## Configuration

Set the recipients (comma- or whitespace-separated age public keys) in
`odoo.conf`, via the `ODOO_AGE_RECIPIENTS` environment variable:

```
age_recipients = age1consumer... age1offsite...
```

The dump is encrypted to all recipients; any single matching identity
decrypts it. With no recipients configured the backup route returns a plain
zip, exactly like stock Odoo.

## Decrypting

```
age -d -i identity.txt -o backup.zip backup.zip.age
```

Restore through `/web/database/restore` expects the decrypted zip; the
manager itself never sees the private key.
