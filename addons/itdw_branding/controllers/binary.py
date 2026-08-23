import logging

from odoo import http
from odoo.addons.web.controllers.binary import Binary
from odoo.http import request
from odoo.tools.misc import file_path

_logger = logging.getLogger(__name__)

NEUTRALIZED_LOGO = "itdw_branding/static/src/img/itdw_logo_neutralized.png"


class ItdwBrandingBinary(Binary):
    @http.route()
    def company_logo(self, dbname=None, **kw):
        if request.db and self._itdw_is_neutralized():
            try:
                return http.Stream.from_path(file_path(NEUTRALIZED_LOGO)).get_response()
            except Exception:
                _logger.warning(
                    "Neutralized logo missing at %s, serving default",
                    NEUTRALIZED_LOGO,
                    exc_info=True,
                )
        return super().company_logo(dbname=dbname, **kw)

    @staticmethod
    def _itdw_is_neutralized():
        # Mirrors odoo/addons/base/models/ir_cron.py: presence of a truthy
        # `database.is_neutralized` config parameter is the canonical signal.
        # Only reached with `request.db` set, so the env and cursor exist —
        # the same branch of the overridden route queries res_company directly.
        return bool(
            request.env["ir.config_parameter"]
            .sudo()
            .get_param("database.is_neutralized")
        )
