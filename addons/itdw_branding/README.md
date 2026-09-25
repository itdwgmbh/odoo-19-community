# IT-DW Branding

Applies the IT-DW corporate identity (https://www.it-dw.com/ci) to the Odoo
backend, login page, QWeb reports and notification emails.

## Colors

Tokens and their Odoo variables are in `static/src/scss/itdw_colors.scss`.
`$o-theme-text-colors` carries darkened variants so contextual text clears
4.5:1 on white — the CI fill values do not.

`itdw_colors.scss` loads before `web/static/src/scss/primary_variables.scss`.
Odoo derives brand variables from each other at parse time behind `!default`,
and SCSS variables are not reactive, so anything assigned after that file has
no effect on already-derived values.

`itdw_colors_dark.scss` loads before the light file inside `web.assets_web_dark`
and assigns without `!default`, so it wins there. Odoo Community's
`ir.http.color_scheme()` always returns `light`, so that bundle is only reached
once a module supplies a dark color scheme.

## Typography

Armata (headings) and Open Sans (body) are self-hosted under `static/src/fonts`.
`$o-system-fonts` is overridden rather than `$o-font-family-sans-serif`, because
the frontend derives its own `$font-family-sans-serif` from `$o-system-fonts`.

## Web client

- `itdw_appsbar` — vertical app sidebar with the IT-DW logo. Hidden on small
  screens, in the website builder, and on the home menu.
- `itdw_appsmenu` — replaces Odoo's apps dropdown with a fullscreen tile grid.
  Any printable keystroke while it is open opens the command palette filtered to
  the menu namespace. Desktop only; mobile keeps Odoo's drawer.
- `webclient.scss` re-lays the web client as a CSS grid so the sidebar gets its
  own column.

Background image paths in these SCSS files must be written as literal
`url("/itdw_branding/...")`. The asset pipeline resolves relative paths against
the containing file's directory and only recognises a root-relative path when
the literal starts with `/`; a path arriving through a SCSS variable or mixin
argument is quoted, gets prefixed, and silently invalidates the whole
`background` shorthand.

## Emails

- CTA button colors come from `res.company.email_secondary_color` and
  `email_primary_color`, written on install and on every upgrade.
- The notification footer names the sending company instead of Odoo. Odoo 19
  renders that footer only when the sender passes
  `email_notification_allow_footer` or `email_notification_force_footer` in the
  context; by default no footer is emitted at all.
- Activity-assignment mails append the activity note, falling back to the
  activity type's `default_note`.

## Neutralized databases

When `database.is_neutralized` is set (by `odoo-bin neutralize`), the favicon,
the appsbar and apps-menu logo, and `/web/binary/company_logo` swap to
TEST-badged variants. The parameter is read through the ORM cache, so a value
changed on a running server takes effect after a restart.

## Company logo

`res.company.logo` is seeded on install only (`noupdate="1"`), so replacing the
logo in Settings → Companies survives later module upgrades.
