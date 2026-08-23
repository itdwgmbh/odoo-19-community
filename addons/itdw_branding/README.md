# IT-DW Branding

Applies the IT-DW corporate identity (https://www.it-dw.com/ci) to the Odoo
backend, login page, QWeb reports and notification emails.

## Tokens

| CI token | Value | Odoo variable | Drives |
| --- | --- | --- | --- |
| Primary | `#B92025` | `$o-brand-primary`, `$o-action`, `$o-enterprise-color` | Buttons, links, active states, frontend `$primary` |
| Dark | `#333333` | `$o-brand-odoo` | Navbar background (`$o-navbar-background`) |
| Secondary | `#6C6E70` | `$o-brand-secondary` | Muted UI accents |
| Success / Info / Warning / Danger | `#28a745` / `#17a2b8` / `#ffc107` / `#FF5733` | `$o-success` … `$o-danger` | Alerts, badges, contextual buttons |

`$o-theme-text-colors` carries darkened variants of the same roles so contextual
text clears 4.5:1 on white — the CI fill values do not.

`static/src/scss/itdw_colors.scss` loads **before**
`web/static/src/scss/primary_variables.scss`. Odoo derives brand variables from
each other at parse time behind `!default`, and SCSS variables are not reactive,
so anything assigned after that file has no effect on already-derived values.

`itdw_colors_dark.scss` loads before the light file inside `web.assets_web_dark`
and assigns without `!default`, so it wins there while the light file's
`!default` clauses keep it out of every other bundle. Odoo Community's
`ir.http.color_scheme()` always returns `light`, so that bundle is only reached
once a module supplies a dark color scheme.

## Typography

Armata (headings) and Open Sans (body) ship as self-hosted woff2 under
`static/src/fonts` — latin and latin-ext subsets, SIL OFL 1.1, see `OFL.txt`.
`$o-system-fonts` is overridden rather than `$o-font-family-sans-serif`, because
the frontend derives its own `$font-family-sans-serif` from `$o-system-fonts`.

## Web client

- `itdw_appsbar` — vertical app sidebar, 180px, `#222222`, red left-edge accent
  on the active app, IT-DW logo pinned to the bottom. Hidden below `md`, in the
  website builder, and on the home menu.
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

- CTA button background comes from `res.company.email_secondary_color`
  (`#B92025`), its label from `email_primary_color` (`#FFFFFF`). Both are written
  on install and on every upgrade.
- The notification footer names the sending company instead of Odoo. Odoo 19
  renders that footer only when the sender passes
  `email_notification_allow_footer` or `email_notification_force_footer` in the
  context; by default no footer is emitted at all.
- Activity-assignment mails append the activity note, falling back to the
  activity type's `default_note`. Odoo's stock template renders only
  document, summary and deadline.

## Neutralized databases

When `database.is_neutralized` is set (by `odoo-bin neutralize`), the favicon,
the appsbar and apps-menu logo, and `/web/binary/company_logo` swap to
TEST-badged variants. `ir.http.session_info` exposes the flag to the web client
for the statically served images. The parameter is read through the ORM cache,
so a value changed on a running server takes effect after a restart.

## Company logo

`res.company.logo` is seeded from `static/src/img/itdw_logo.png` on install
only. The record sits under `noupdate="1"` so replacing the logo in
Settings → Companies survives later module upgrades.
