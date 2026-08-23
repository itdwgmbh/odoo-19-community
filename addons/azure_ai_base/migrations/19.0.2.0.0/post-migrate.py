"""Drop the credential keys this addon no longer reads.

1.x carried its own `azure.auth.service` reading `azure_auth.*` and falling
back to `ms_graph.*`. 2.0 authenticates through `ms.entra.auth`, which reads
only `ms_graph.*`. Leaving the old rows behind would leave configuration on
screen that no longer has any effect — and on a database where the two pointed
at different app registrations, silently at that.
"""

import logging

_logger = logging.getLogger(__name__)

OBSOLETE_KEYS = (
    "azure_auth.tenant_id",
    "azure_auth.client_id",
    "azure_auth.client_secret",
)


def migrate(cr, version):
    cr.execute(
        "DELETE FROM ir_config_parameter WHERE key IN %s RETURNING key",
        (OBSOLETE_KEYS,),
    )
    removed = [row[0] for row in cr.fetchall()]
    if removed:
        _logger.info(
            "azure_ai_base_dropped_obsolete_credentials",
            extra={
                "event": "azure_ai_base_dropped_obsolete_credentials",
                "keys": removed,
            },
        )
