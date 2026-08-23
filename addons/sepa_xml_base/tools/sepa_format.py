"""Value helpers for the SEPA subset of ISO 20022.

Pure functions, no Odoo imports: character set, IBAN, BIC, creditor
identifier, amounts, dates and identifiers, in the shape the pain.001 and
pain.008 schemas expect.
"""

import re
import unicodedata
import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Field lengths of the SEPA scheme (EPC125-05 / EPC130-08).
MAX_ID = 35
MAX_NAME = 70
MAX_ADDRESS_LINE = 70
MAX_ADDRESS_LINES = 2
MAX_REMITTANCE = 140

MAX_AMOUNT = Decimal("999999999.99")

# Characters a SEPA message may carry.
ALLOWED_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/-?:().,'+ "
)

# Applied before NFKD, where the German transliteration differs from simply
# dropping the accent, plus symbols with an accepted SEPA equivalent.
_SUBSTITUTIONS = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "Ä": "Ae",
    "Ö": "Oe",
    "Ü": "Ue",
    "ß": "ss",
    "æ": "ae",
    "Æ": "Ae",
    "œ": "oe",
    "Œ": "Oe",
    "ø": "oe",
    "Ø": "Oe",
    "å": "aa",
    "Å": "Aa",
    "ł": "l",
    "Ł": "L",
    "đ": "d",
    "Đ": "D",
    "ð": "d",
    "Ð": "D",
    "þ": "th",
    "Þ": "Th",
    "&": "+",
    '"': "'",
    "„": "'",
    "“": "'",
    "”": "'",
    "‘": "'",
    "’": "'",
    "–": "-",
    "—": "-",
    "_": "-",
    "€": "EUR",
}

_IBAN_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")
_BIC_RE = re.compile(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$")
_CREDITOR_ID_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Za-z0-9]{3}[A-Za-z0-9]{1,28}$")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_CODE_RE = re.compile(r"^[A-Za-z0-9]{1,4}$")


class SepaValidationError(ValueError):
    """Content the SEPA schemas or the EPC rulebooks would reject."""


def sanitize(value, max_length=None):
    """Map `value` onto the SEPA character set, collapsing whitespace.

    Unsupported characters are transliterated where an accepted equivalent
    exists and replaced by a space otherwise. Truncates to `max_length`.
    """
    if value is None:
        return ""
    text = "".join(_SUBSTITUTIONS.get(char, char) for char in str(value))
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = "".join(char if char in ALLOWED_CHARS else " " for char in text)
    text = " ".join(text.split())
    if max_length:
        text = text[:max_length]
    return text.strip()


def required_text(value, field, max_length=None):
    """Sanitize a mandatory field, refusing a value that sanitizes to nothing."""
    text = sanitize(value, max_length)
    if not text:
        raise SepaValidationError(f"{field} is required")
    return text


def normalize_iban(value, field="IBAN"):
    """Return the IBAN without separators, after the ISO 7064 mod-97 check."""
    iban = re.sub(r"\s+", "", str(value or "")).upper()
    if not _IBAN_RE.match(iban):
        raise SepaValidationError(f"{field} {value!r} is not a valid IBAN")
    rearranged = iban[4:] + iban[:4]
    if int("".join(str(int(char, 36)) for char in rearranged)) % 97 != 1:
        raise SepaValidationError(f"{field} {iban} fails the IBAN check digits")
    return iban


def normalize_bic(value, field="BIC"):
    """Return the BIC in upper case, or "" when none was given."""
    bic = re.sub(r"\s+", "", str(value or "")).upper()
    if not bic:
        return ""
    if not _BIC_RE.match(bic):
        raise SepaValidationError(f"{field} {value!r} is not a valid BIC")
    return bic


def normalize_creditor_identifier(value, field="creditor_scheme_id"):
    """Return the SEPA creditor identifier after its mod-97 check.

    The check runs over the identifier without the three-character creditor
    business code, which carries no check-digit meaning.
    """
    identifier = re.sub(r"\s+", "", str(value or "")).upper()
    if not _CREDITOR_ID_RE.match(identifier):
        raise SepaValidationError(
            f"{field} {value!r} is not a valid SEPA creditor identifier"
        )
    national = identifier[7:]
    rearranged = national + identifier[:4]
    if int("".join(str(int(char, 36)) for char in rearranged)) % 97 != 1:
        raise SepaValidationError(f"{field} {identifier} fails its check digits")
    return identifier


def normalize_country(value, field="country"):
    country = str(value or "").strip().upper()
    if country and not _COUNTRY_RE.match(country):
        raise SepaValidationError(f"{field} {value!r} is not an ISO 3166 country code")
    return country


def normalize_currency(value, field="currency"):
    currency = str(value or "EUR").strip().upper()
    if not _CURRENCY_RE.match(currency):
        raise SepaValidationError(f"{field} {value!r} is not an ISO 4217 currency code")
    return currency


def normalize_code(value, field):
    """Return an ISO 20022 external code (purpose, category purpose, ...)."""
    code = str(value or "").strip().upper()
    if code and not _CODE_RE.match(code):
        raise SepaValidationError(f"{field} {value!r} is not an ISO 20022 code")
    return code


def to_decimal(value, field="amount"):
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError, TypeError) as e:
        raise SepaValidationError(f"{field} {value!r} is not a number") from e
    if not amount.is_finite():
        raise SepaValidationError(f"{field} {value!r} is not a number")
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_amount(value, field="amount"):
    """Return the amount as the schema's two-decimal string."""
    amount = to_decimal(value, field)
    if amount <= 0:
        raise SepaValidationError(f"{field} {value!r} must be greater than zero")
    if amount > MAX_AMOUNT:
        raise SepaValidationError(f"{field} {value!r} exceeds {MAX_AMOUNT}")
    return f"{amount:f}"


def to_date(value, field="date"):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as e:
        raise SepaValidationError(f"{field} {value!r} is not a date") from e


def format_date(value, field="date"):
    return to_date(value, field).isoformat()


def to_datetime(value, field="creation_date_time"):
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        moment = datetime(value.year, value.month, value.day, tzinfo=UTC)
    else:
        text = str(value).strip()
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as e:
            raise SepaValidationError(f"{field} {value!r} is not a timestamp") from e
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def format_datetime(value=None, field="creation_date_time"):
    """Return the UTC timestamp the schema's ISODateTime expects."""
    moment = datetime.now(UTC) if value is None else to_datetime(value, field)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_id(prefix=""):
    """Return a unique message or payment identifier of at most 35 characters."""
    token = uuid.uuid4().hex.upper()
    prefix = sanitize(prefix, 10).replace(" ", "")
    return (f"{prefix}-{token}" if prefix else token)[:MAX_ID]
