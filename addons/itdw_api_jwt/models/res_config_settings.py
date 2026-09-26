from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    api_jwt_only = fields.Boolean(
        string="Require JWTs for bearer routes",
        config_parameter="api_jwt.jwt_only",
        help="Reject API keys and browser sessions on routes that use bearer authentication.",
    )
