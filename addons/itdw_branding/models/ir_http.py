from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        # Surfaces `database.is_neutralized` to the web client so OWL
        # components (e.g. the appsbar) can swap statically-served logos
        # that don't go through the company_logo controller.
        info = super().session_info()
        info["is_neutralized"] = bool(
            self.env["ir.config_parameter"].sudo().get_param("database.is_neutralized")
        )
        return info
