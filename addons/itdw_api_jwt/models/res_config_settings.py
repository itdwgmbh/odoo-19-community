from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    api_jwt_only = fields.Boolean(
        string="Require JWTs for JSON-2",
        config_parameter="api_jwt.jwt_only",
        help="Reject API keys and browser sessions on /json/2/. Other routes keep their existing authentication.",
    )
