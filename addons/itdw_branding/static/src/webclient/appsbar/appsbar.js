/*
 * IT-DW apps sidebar — vertical bar of installed-app icons.
 */

import { Component, onWillUnmount } from "@odoo/owl";
import { session } from "@web/session";
import { useService } from "@web/core/utils/hooks";

// Static dark-mode logo shipped with this module. Distinct from
// res.company.logo (which is light-mode and used by navbar / login) — the
// appsbar background is dark, so we need the dark-background variant.
// The `_neutralized` variant carries a TEST badge and is selected when
// session_info reports `is_neutralized` (set by `odoo-bin neutralize`).
const APPSBAR_LOGO_URL = "/itdw_branding/static/src/img/itdw_logo_dark.svg";
const APPSBAR_LOGO_URL_NEUTRALIZED =
    "/itdw_branding/static/src/img/itdw_logo_dark_neutralized.svg";

export class AppsBar extends Component {
    static template = "itdw_branding.AppsBar";
    static props = {};

    setup() {
        this.appMenu = useService("itdw_app_menu");
        this.logoUrl = session.is_neutralized
            ? APPSBAR_LOGO_URL_NEUTRALIZED
            : APPSBAR_LOGO_URL;
        // Re-render when the user navigates between apps so the active
        // highlight follows them without manual subscription bookkeeping
        // in every callsite.
        const onAppChanged = () => this.render();
        this.env.bus.addEventListener("MENUS:APP-CHANGED", onAppChanged);
        onWillUnmount(() => {
            this.env.bus.removeEventListener("MENUS:APP-CHANGED", onAppChanged);
        });
    }

    get apps() {
        return this.appMenu.getAppsMenuItems();
    }

    get currentAppId() {
        return this.appMenu.getCurrentApp()?.id;
    }
}
