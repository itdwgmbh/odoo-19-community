import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { dateField, dateTimeField } from "@web/views/fields/datetime/datetime_field";
import { formatDate, formatDateTime } from "@web/views/fields/formatters";
import { Message } from "@mail/core/common/message_model";

function numericByDefault(formatter) {
    const wrapped = (value, options = {}) => formatter(value, { numeric: true, ...options });
    wrapped.extractOptions = ({ attrs, options }) =>
        formatter.extractOptions({ attrs, options: { numeric: true, ...options } });
    return wrapped;
}

registry.category("formatters")
    .add("date", numericByDefault(formatDate), { force: true })
    .add("datetime", numericByDefault(formatDateTime), { force: true });

for (const field of [dateField, dateTimeField]) {
    patch(field, {
        extractProps({ options, ...rest }, dynamicInfo) {
            return super.extractProps({ options: { numeric: true, ...options }, ...rest }, dynamicInfo);
        },
    });
}

patch(Message.prototype, {
    get dateDay() {
        return this.datetime.toLocaleString(luxon.DateTime.DATE_MED, { locale: user.lang });
    },
    get dateSimpleWithDay() {
        return this.datetime.toLocaleString(luxon.DateTime.DATETIME_MED, { locale: user.lang });
    },
});
