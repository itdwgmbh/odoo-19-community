from odoo import api, fields, models
from odoo.exceptions import ValidationError


class JwtIssuer(models.Model):
    _name = "api.jwt.issuer"
    _description = "Trusted JWT issuer for the JSON-2 API"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    issuer = fields.Char(string="Issuer (iss)", required=True)
    audience = fields.Char(string="Audience (aud)", required=True)
    jwks_url = fields.Char(string="JWKS URL", required=True)
    user_claim = fields.Char(
        string="Odoo login claim",
        required=True,
        default="sub",
        help="The JWT claim whose value exactly matches an Odoo user's login.",
    )

    _issuer_unique = models.Constraint(
        "UNIQUE (issuer)", "The JWT issuer must be unique."
    )

    @api.constrains("jwks_url")
    def _check_jwks_url(self):
        for issuer in self:
            if not issuer.jwks_url.startswith("https://"):
                raise ValidationError("The JWKS URL must use HTTPS.")
