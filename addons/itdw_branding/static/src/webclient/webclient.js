/*
 * Patch Odoo's WebClient to register the IT-DW AppsBar component so it can
 * be referenced from the inherited WebClient template.
 */

import { patch } from "@web/core/utils/patch";
import { WebClient } from "@web/webclient/webclient";
import { AppsBar } from "@itdw_branding/webclient/appsbar/appsbar";

patch(WebClient, {
    components: {
        ...WebClient.components,
        AppsBar,
    },
});
