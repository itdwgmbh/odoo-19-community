{
    "name": "IT-DW Branding",
    "version": "19.0.1.0.0",
    "category": "Customizations",
    "summary": "IT-DW corporate identity for the Odoo backend, login, emails and reports",
    "description": """
Applies IT-DW corporate identity (https://www.it-dw.com/ci) across Odoo:

- Backend, frontend and report SCSS overriding Odoo brand colors with IT-DW
  tokens (red #B92025, gray #6C6E70, dark #333333; lightened in dark mode)
- Self-hosted Armata (headings) and Open Sans (body) webfonts
- Apps sidebar and fullscreen apps menu replacing Odoo's dropdown list
- Branded mail notification layout footer
- Activity-assignment email enriched with the activity note
- Company logo seeded from the IT-DW logo shipped under static assets
- On neutralized databases, swaps favicon, appsbar logo and
  /web/binary/company_logo for TEST-marked variants so prod and staging are
  visually distinct
""",
    "author": "IT-DW GmbH",
    "license": "LGPL-3",
    "website": "https://www.it-dw.com",
    "depends": ["mail", "web"],
    "data": [
        "data/itdw_branding_layout.xml",
        "data/itdw_branding_activity.xml",
        "data/itdw_branding_company.xml",
        "data/itdw_branding_favicon.xml",
    ],
    "assets": {
        # Load BEFORE Odoo's primary_variables.scss so our values become the
        # originals. Odoo's $o-brand-odoo / $o-brand-primary / $o-action use
        # `!default` and derive from $o-community-color at parse time — SCSS
        # variables are not reactive, so reassigning later has no effect on
        # already-derived variables (e.g. $o-navbar-background).
        "web._assets_primary_variables": [
            (
                "before",
                "web/static/src/scss/primary_variables.scss",
                "itdw_branding/static/src/scss/itdw_colors.scss",
            ),
        ],
        # Dark mode. `web.assets_web_dark` includes `web.assets_web`, so the
        # light token file is already in the expanded list by the time this
        # entry is processed and can be targeted. Loading the dark file first
        # wins because itdw_colors.scss declares its tokens with `!default`.
        "web.assets_web_dark": [
            (
                "before",
                "itdw_branding/static/src/scss/itdw_colors.scss",
                "itdw_branding/static/src/scss/itdw_colors_dark.scss",
            ),
        ],
        # Apps sidebar + apps menu — registered after the WebClient / NavBar
        # components they patch so the parent classes are fully defined
        # before we extend them.
        "web.assets_backend": [
            "itdw_branding/static/src/scss/itdw_fonts.scss",
            "itdw_branding/static/src/webclient/webclient.scss",
            "itdw_branding/static/src/webclient/appsbar/appsbar.scss",
            "itdw_branding/static/src/webclient/appsmenu/appsmenu.scss",
            "itdw_branding/static/src/webclient/menus/app_menu_service.js",
            (
                "after",
                "web/static/src/webclient/webclient.js",
                "itdw_branding/static/src/webclient/appsbar/appsbar.js",
            ),
            (
                "after",
                "web/static/src/webclient/webclient.js",
                "itdw_branding/static/src/webclient/webclient.js",
            ),
            (
                "after",
                "web/static/src/webclient/navbar/navbar.js",
                "itdw_branding/static/src/webclient/appsmenu/appsmenu.js",
            ),
            (
                "after",
                "web/static/src/webclient/navbar/navbar.js",
                "itdw_branding/static/src/webclient/navbar/navbar.js",
            ),
            "itdw_branding/static/src/webclient/appsbar/appsbar.xml",
            "itdw_branding/static/src/webclient/webclient.xml",
            "itdw_branding/static/src/webclient/navbar/navbar.xml",
        ],
        # Login / portal and QWeb PDF reports pick up the same faces.
        "web.assets_frontend": [
            "itdw_branding/static/src/scss/itdw_fonts.scss",
        ],
        "web.report_assets_common": [
            "itdw_branding/static/src/scss/itdw_fonts.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
