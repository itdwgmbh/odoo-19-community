/*
 * Wire the IT-DW AppsMenu component into the standard NavBar so the
 * inherited template (navbar.xml) can render it, and expose the
 * itdw_app_menu service on the NavBar instance for the template's
 * `this.appMenuService` references.
 */

import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
import { useService } from "@web/core/utils/hooks";
import { NavBar } from "@web/webclient/navbar/navbar";
import { AppsMenu } from "@itdw_branding/webclient/appsmenu/appsmenu";

patch(NavBar.prototype, {
    setup() {
        super.setup();
        this.appMenuService = useService("itdw_app_menu");
        this.itdwAppsmenuClass = session.is_neutralized
            ? "itdw_appsmenu itdw_appsmenu_neutralized"
            : "itdw_appsmenu";
    },
});

patch(NavBar, {
    components: {
        ...NavBar.components,
        AppsMenu,
    },
});
