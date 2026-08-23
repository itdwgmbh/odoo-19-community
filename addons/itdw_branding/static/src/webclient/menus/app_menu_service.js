/*
 * Service that exposes a flat list of installed apps for the IT-DW appsbar,
 * built on top of Odoo's "menu" service.
 */

import { registry } from "@web/core/registry";

function inferIconUrl(item) {
    if (!item.webIconData) {
        // Fallback to Odoo's default app icon shipped with `base`.
        return "/base/static/description/icon.png";
    }
    if (item.webIconData.startsWith("data:image")) {
        return item.webIconData;
    }
    // webIconData is base64; the leading byte tells us SVG vs PNG.
    const mime = item.webIconData.startsWith("P") ? "image/svg+xml" : "image/png";
    return `data:${mime};base64,` + item.webIconData.replace(/\s/g, "");
}

function buildHref(item) {
    const parts = [`menu_id=${item.id}`];
    if (item.actionID) {
        parts.push(`action=${item.actionID}`);
    }
    return "#" + parts.join("&");
}

export const itdwAppMenuService = {
    dependencies: ["menu"],
    start(env, { menu }) {
        return {
            getCurrentApp() {
                return menu.getCurrentApp();
            },
            getAppsMenuItems() {
                return menu.getApps().map((item) => ({
                    id: item.id,
                    name: item.name,
                    xmlid: item.xmlid,
                    appID: item.appID,
                    actionID: item.actionID,
                    iconUrl: inferIconUrl(item),
                    href: buildHref(item),
                    action: () => menu.selectMenu(item),
                }));
            },
        };
    },
};

registry.category("services").add("itdw_app_menu", itdwAppMenuService);
