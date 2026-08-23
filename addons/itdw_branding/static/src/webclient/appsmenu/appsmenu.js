/*
 * IT-DW apps menu — fullscreen tile grid replacement for Odoo's vertical
 * apps dropdown.
 *
 * While the menu is open, any printable keystroke opens the command
 * palette pre-filtered to the menu namespace ("/<key>") so users can
 * jump to a deep menu entry by typing.
 */

import { useEffect } from "@odoo/owl";
import { useBus, useService } from "@web/core/utils/hooks";
import { Dropdown } from "@web/core/dropdown/dropdown";

export class AppsMenu extends Dropdown {
    setup() {
        super.setup();
        this.commandService = useService("command");
        this._commandPaletteOpen = false;
        useEffect(
            (isOpen) => {
                if (!isOpen) {
                    return;
                }
                const onKeydown = (ev) => {
                    if (
                        this._commandPaletteOpen ||
                        ev.key.length !== 1 ||
                        ev.ctrlKey ||
                        ev.altKey ||
                        ev.metaKey
                    ) {
                        return;
                    }
                    this._commandPaletteOpen = true;
                    this.commandService.openMainPalette(
                        { searchValue: `/${ev.key}` },
                        () => {
                            this._commandPaletteOpen = false;
                        },
                    );
                };
                window.addEventListener("keydown", onKeydown);
                return () => {
                    window.removeEventListener("keydown", onKeydown);
                    this._commandPaletteOpen = false;
                };
            },
            () => [this.state.isOpen],
        );
        // Close the menu when the user navigates to an action (clicking a
        // tile fires this via the menu service).
        useBus(this.env.bus, "ACTION_MANAGER:UI-UPDATED", () => this.state.close());
    }
}
