import logging
from decimal import Decimal

from lxml import etree
from odoo import fields, models

from ..tools import sepa_format as fmt
from ..tools.sepa_format import SepaValidationError

_logger = logging.getLogger(__name__)

SCHEMA_PREFIX = "urn:iso:std:iso:20022:tech:xsd:"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

CREDIT_TRANSFER = "credit_transfer"
DIRECT_DEBIT = "direct_debit"

BODY_ELEMENT = {
    CREDIT_TRANSFER: "CstmrCdtTrfInitn",
    DIRECT_DEBIT: "CstmrDrctDbtInitn",
}
DOCUMENT_TYPE_BY_BODY = {body: kind for kind, body in BODY_ELEMENT.items()}

# Versions this addon writes. `bic_tag` and `dated_execution` are the two
# places the SEPA subset of pain.001/pain.008 changed between the 2009 and the
# 2019 message definitions; `smnda_in_account` follows the EPC rulebook move of
# the "same mandate, new debtor account" flag from the agent to the account.
VERSIONS = {
    "pain.001.001.03": {
        "type": CREDIT_TRANSFER,
        "bic_tag": "BIC",
        "dated_execution": False,
    },
    "pain.001.001.09": {
        "type": CREDIT_TRANSFER,
        "bic_tag": "BICFI",
        "dated_execution": True,
    },
    "pain.008.001.02": {
        "type": DIRECT_DEBIT,
        "bic_tag": "BIC",
        "smnda_in_account": False,
    },
    "pain.008.001.08": {
        "type": DIRECT_DEBIT,
        "bic_tag": "BICFI",
        "smnda_in_account": True,
    },
}
DEFAULT_VERSION = {
    CREDIT_TRANSFER: "pain.001.001.09",
    DIRECT_DEBIT: "pain.008.001.08",
}

# Agents the schema makes mandatory: without a BIC they carry the EPC's
# IBAN-only placeholder.
NOT_PROVIDED = "NOTPROVIDED"
SMNDA = "SMNDA"

SEQUENCE_TYPES = ("FRST", "RCUR", "OOFF", "FNAL")
CHARGE_BEARERS = ("SLEV", "CRED", "DEBT", "SHAR")


def _sub(parent, tag, text=None):
    """Append a child in the parent's namespace."""
    node = etree.SubElement(parent, f"{{{etree.QName(parent).namespace}}}{tag}")
    if text is not None:
        node.text = text
    return node


def _find(node, path):
    ns = etree.QName(node).namespace
    return node.find("/".join(f"{{{ns}}}{step}" for step in path.split("/")))


def _text(node, path):
    found = _find(node, path)
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def _children(node, tag):
    return node.findall(f"{{{etree.QName(node).namespace}}}{tag}")


def _read_xml(source):
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False
    )
    if isinstance(source, str):
        source = source.encode()
    if isinstance(source, bytes | bytearray):
        return etree.fromstring(bytes(source), parser=parser)
    return etree.parse(source, parser=parser).getroot()


class SepaXml(models.AbstractModel):
    _name = "sepa.xml"
    _description = "SEPA credit transfer and direct debit XML"

    # -- creating ---------------------------------------------------------

    def _build_credit_transfer(self, payload, version=None):
        """Return (True, xml_bytes) for a SEPA credit transfer (pain.001)."""
        return self._build(payload, CREDIT_TRANSFER, version)

    def _build_direct_debit(self, payload, version=None):
        """Return (True, xml_bytes) for a SEPA direct debit (pain.008)."""
        return self._build(payload, DIRECT_DEBIT, version)

    def _build(self, payload, document_type, version=None):
        version = version or DEFAULT_VERSION[document_type]
        try:
            return True, self._render(payload, document_type, version)
        except SepaValidationError as e:
            _logger.warning(
                "sepa_build_failed",
                extra={
                    "event": "sepa_build_failed",
                    "document_type": document_type,
                    "version": version,
                    "error": str(e),
                },
            )
            return False, str(e)

    def _render(self, payload, document_type, version):
        flags = VERSIONS.get(version)
        if not flags or flags["type"] != document_type:
            supported = ", ".join(
                sorted(k for k, v in VERSIONS.items() if v["type"] == document_type)
            )
            raise SepaValidationError(
                f"{version!r} is not a supported {document_type} version "
                f"(supported: {supported})"
            )
        if not isinstance(payload, dict):
            raise SepaValidationError("payload must be a dict")
        payments = payload.get("payments")
        if not isinstance(payments, list | tuple) or not payments:
            raise SepaValidationError(
                "payload['payments'] must hold at least one payment block"
            )

        namespace = f"{SCHEMA_PREFIX}{version}"
        root = etree.Element(
            f"{{{namespace}}}Document", nsmap={None: namespace, "xsi": XSI_NS}
        )
        root.set(f"{{{XSI_NS}}}schemaLocation", f"{namespace} {version}.xsd")
        body = _sub(root, BODY_ELEMENT[document_type])

        count = 0
        total = Decimal("0.00")
        for index, payment in enumerate(payments, start=1):
            block_count, block_total = self._render_payment(
                body, payment, index, document_type, flags
            )
            count += block_count
            total += block_total

        body.insert(0, self._render_group_header(namespace, payload, count, total))
        return etree.tostring(
            root, xml_declaration=True, encoding="UTF-8", pretty_print=True
        )

    def _render_group_header(self, namespace, payload, count, total):
        header = payload.get("group_header") or payload
        group = etree.Element(f"{{{namespace}}}GrpHdr")
        _sub(
            group,
            "MsgId",
            fmt.sanitize(header.get("message_id"), fmt.MAX_ID) or fmt.generate_id(),
        )
        _sub(group, "CreDtTm", fmt.format_datetime(header.get("creation_date_time")))
        _sub(group, "NbOfTxs", str(count))
        _sub(group, "CtrlSum", f"{total:f}")
        self._add_party(
            group, "InitgPty", header.get("initiating_party"), "initiating party"
        )
        return group

    def _render_payment(self, body, payment, index, document_type, flags):
        if not isinstance(payment, dict):
            raise SepaValidationError(f"payment block {index} must be a dict")
        transactions = payment.get("transactions")
        if not isinstance(transactions, list | tuple) or not transactions:
            raise SepaValidationError(f"payment block {index} has no transactions")
        credit_transfer = document_type == CREDIT_TRANSFER

        node = _sub(body, "PmtInf")
        _sub(
            node,
            "PmtInfId",
            fmt.sanitize(payment.get("payment_id"), fmt.MAX_ID) or fmt.generate_id(),
        )
        _sub(node, "PmtMtd", "TRF" if credit_transfer else "DD")
        batch_booking = payment.get("batch_booking")
        if batch_booking is not None:
            _sub(node, "BtchBookg", "true" if batch_booking else "false")
        totals_at = len(node)

        self._add_payment_type(node, payment, document_type)
        requested_date = fmt.format_date(
            payment.get("requested_date") or fields.Date.context_today(self),
            "requested_date",
        )
        if credit_transfer:
            if flags["dated_execution"]:
                _sub(_sub(node, "ReqdExctnDt"), "Dt", requested_date)
            else:
                _sub(node, "ReqdExctnDt", requested_date)
            self._add_party(node, "Dbtr", payment.get("debtor"), "debtor")
            self._add_account(node, "DbtrAcct", payment.get("debtor"), "debtor")
            self._add_agent(node, "DbtrAgt", payment.get("debtor"), "debtor", flags)
            self._add_ultimate(node, "UltmtDbtr", payment.get("ultimate_debtor"))
        else:
            _sub(node, "ReqdColltnDt", requested_date)
            self._add_party(node, "Cdtr", payment.get("creditor"), "creditor")
            self._add_account(node, "CdtrAcct", payment.get("creditor"), "creditor")
            self._add_agent(node, "CdtrAgt", payment.get("creditor"), "creditor", flags)
            self._add_ultimate(node, "UltmtCdtr", payment.get("ultimate_creditor"))
        charge_bearer = fmt.normalize_code(
            payment.get("charge_bearer") or "SLEV", "charge_bearer"
        )
        if charge_bearer not in CHARGE_BEARERS:
            raise SepaValidationError(
                f"charge_bearer must be one of {', '.join(CHARGE_BEARERS)}"
            )
        _sub(node, "ChrgBr", charge_bearer)
        if not credit_transfer:
            self._add_creditor_scheme_id(node, payment.get("creditor_scheme_id"))

        total = Decimal("0.00")
        for position, transaction in enumerate(transactions, start=1):
            if not isinstance(transaction, dict):
                raise SepaValidationError(
                    f"transaction {position} of payment block {index} must be a dict"
                )
            label = f"transaction {position} of payment block {index}"
            if credit_transfer:
                total += self._render_credit_transfer_transaction(
                    node, transaction, label, flags
                )
            else:
                total += self._render_direct_debit_transaction(
                    node, transaction, label, flags
                )

        count = len(transactions)
        number = _sub(node, "NbOfTxs", str(count))
        control_sum = _sub(node, "CtrlSum", f"{total:f}")
        node.insert(totals_at, number)
        node.insert(totals_at + 1, control_sum)
        return count, total

    def _render_credit_transfer_transaction(self, parent, transaction, label, flags):
        node = _sub(parent, "CdtTrfTxInf")
        self._add_payment_id(node, transaction)
        amount, text = self._amount(transaction, label)
        amt = _sub(node, "Amt")
        instructed = _sub(amt, "InstdAmt", text)
        instructed.set("Ccy", fmt.normalize_currency(transaction.get("currency")))
        creditor = transaction.get("creditor")
        self._add_agent(node, "CdtrAgt", creditor, f"{label} creditor", flags, False)
        self._add_party(node, "Cdtr", creditor, f"{label} creditor")
        self._add_account(node, "CdtrAcct", creditor, f"{label} creditor")
        self._add_ultimate(node, "UltmtCdtr", transaction.get("ultimate_creditor"))
        self._add_purpose(node, transaction)
        self._add_remittance(node, transaction)
        return amount

    def _render_direct_debit_transaction(self, parent, transaction, label, flags):
        node = _sub(parent, "DrctDbtTxInf")
        self._add_payment_id(node, transaction)
        amount, text = self._amount(transaction, label)
        instructed = _sub(node, "InstdAmt", text)
        instructed.set("Ccy", fmt.normalize_currency(transaction.get("currency")))
        self._add_mandate(node, transaction.get("mandate"), label, flags)
        debtor = transaction.get("debtor")
        self._add_agent(node, "DbtrAgt", debtor, f"{label} debtor", flags)
        self._add_party(node, "Dbtr", debtor, f"{label} debtor")
        self._add_account(node, "DbtrAcct", debtor, f"{label} debtor")
        self._add_ultimate(node, "UltmtDbtr", transaction.get("ultimate_debtor"))
        self._add_purpose(node, transaction)
        self._add_remittance(node, transaction)
        return amount

    def _amount(self, transaction, label):
        amount = fmt.to_decimal(transaction.get("amount"), f"{label} amount")
        return amount, fmt.format_amount(amount, f"{label} amount")

    def _add_payment_id(self, parent, transaction):
        node = _sub(parent, "PmtId")
        instruction_id = fmt.sanitize(transaction.get("instruction_id"), fmt.MAX_ID)
        if instruction_id:
            _sub(node, "InstrId", instruction_id)
        _sub(
            node,
            "EndToEndId",
            fmt.sanitize(transaction.get("end_to_end_id"), fmt.MAX_ID) or NOT_PROVIDED,
        )

    def _add_payment_type(self, parent, payment, document_type):
        node = _sub(parent, "PmtTpInf")
        _sub(
            _sub(node, "SvcLvl"),
            "Cd",
            fmt.normalize_code(payment.get("service_level") or "SEPA", "service_level"),
        )
        if document_type == DIRECT_DEBIT:
            _sub(
                _sub(node, "LclInstrm"),
                "Cd",
                fmt.normalize_code(
                    payment.get("local_instrument") or "CORE", "local_instrument"
                ),
            )
            sequence_type = (payment.get("sequence_type") or "").strip().upper()
            if sequence_type not in SEQUENCE_TYPES:
                raise SepaValidationError(
                    f"sequence_type must be one of {', '.join(SEQUENCE_TYPES)}"
                )
            _sub(node, "SeqTp", sequence_type)
        category_purpose = fmt.normalize_code(
            payment.get("category_purpose"), "category_purpose"
        )
        if category_purpose:
            _sub(_sub(node, "CtgyPurp"), "Cd", category_purpose)

    def _add_party(self, parent, tag, party, label):
        party = party or {}
        if not isinstance(party, dict):
            raise SepaValidationError(f"{label} must be a dict")
        node = _sub(parent, tag)
        _sub(
            node,
            "Nm",
            fmt.required_text(party.get("name"), f"{label} name", fmt.MAX_NAME),
        )
        country = fmt.normalize_country(party.get("country"), f"{label} country")
        lines = [
            line
            for line in (
                fmt.sanitize(line, fmt.MAX_ADDRESS_LINE)
                for line in (party.get("address_lines") or [])
            )
            if line
        ][: fmt.MAX_ADDRESS_LINES]
        if country or lines:
            address = _sub(node, "PstlAdr")
            if country:
                _sub(address, "Ctry", country)
            for line in lines:
                _sub(address, "AdrLine", line)
        identifier = fmt.sanitize(party.get("identifier"), fmt.MAX_ID)
        if identifier:
            _sub(_sub(_sub(_sub(node, "Id"), "OrgId"), "Othr"), "Id", identifier)
        return node

    def _add_ultimate(self, parent, tag, party):
        if not party:
            return None
        if isinstance(party, str):
            party = {"name": party}
        node = _sub(parent, tag)
        _sub(
            node,
            "Nm",
            fmt.required_text(party.get("name"), f"{tag} name", fmt.MAX_NAME),
        )
        identifier = fmt.sanitize(party.get("identifier"), fmt.MAX_ID)
        if identifier:
            _sub(_sub(_sub(_sub(node, "Id"), "OrgId"), "Othr"), "Id", identifier)
        return node

    def _add_account(self, parent, tag, party, label):
        iban = fmt.normalize_iban((party or {}).get("iban"), f"{label} iban")
        _sub(_sub(_sub(parent, tag), "Id"), "IBAN", iban)

    def _add_agent(self, parent, tag, party, label, flags, required=True):
        bic = fmt.normalize_bic((party or {}).get("bic"), f"{label} bic")
        if not bic and not required:
            return None
        node = _sub(parent, tag)
        institution = _sub(node, "FinInstnId")
        if bic:
            _sub(institution, flags["bic_tag"], bic)
        else:
            _sub(_sub(institution, "Othr"), "Id", NOT_PROVIDED)
        return node

    def _add_creditor_scheme_id(self, parent, value):
        identifier = fmt.normalize_creditor_identifier(value)
        other = _sub(_sub(_sub(_sub(parent, "CdtrSchmeId"), "Id"), "PrvtId"), "Othr")
        _sub(other, "Id", identifier)
        _sub(_sub(other, "SchmeNm"), "Prtry", "SEPA")

    def _add_mandate(self, parent, mandate, label, flags):
        mandate = mandate or {}
        if not isinstance(mandate, dict):
            raise SepaValidationError(f"{label} mandate must be a dict")
        node = _sub(_sub(parent, "DrctDbtTx"), "MndtRltdInf")
        _sub(
            node,
            "MndtId",
            fmt.required_text(mandate.get("id"), f"{label} mandate id", fmt.MAX_ID),
        )
        if not mandate.get("signature_date"):
            raise SepaValidationError(f"{label} mandate signature_date is required")
        _sub(
            node,
            "DtOfSgntr",
            fmt.format_date(
                mandate.get("signature_date"), f"{label} mandate signature_date"
            ),
        )
        amendment = mandate.get("amendment")
        _sub(node, "AmdmntInd", "true" if amendment else "false")
        if amendment:
            self._add_amendment(node, amendment, label, flags)

    def _add_amendment(self, parent, amendment, label, flags):
        if not isinstance(amendment, dict):
            raise SepaValidationError(f"{label} mandate amendment must be a dict")
        original_iban = amendment.get("original_debtor_iban")
        new_debtor_account = amendment.get("same_mandate_new_debtor_account")
        if original_iban and new_debtor_account:
            raise SepaValidationError(
                f"{label} mandate amendment carries both original_debtor_iban and "
                "same_mandate_new_debtor_account"
            )
        node = _sub(parent, "AmdmntInfDtls")
        original_mandate_id = fmt.sanitize(
            amendment.get("original_mandate_id"), fmt.MAX_ID
        )
        if original_mandate_id:
            _sub(node, "OrgnlMndtId", original_mandate_id)
        original_scheme_id = amendment.get("original_creditor_scheme_id")
        original_name = amendment.get("original_creditor_name")
        if original_scheme_id or original_name:
            scheme = _sub(node, "OrgnlCdtrSchmeId")
            if original_name:
                _sub(
                    scheme,
                    "Nm",
                    fmt.required_text(
                        original_name, f"{label} original_creditor_name", fmt.MAX_NAME
                    ),
                )
            if original_scheme_id:
                other = _sub(_sub(_sub(scheme, "Id"), "PrvtId"), "Othr")
                _sub(
                    other,
                    "Id",
                    fmt.normalize_creditor_identifier(
                        original_scheme_id, f"{label} original_creditor_scheme_id"
                    ),
                )
                _sub(_sub(other, "SchmeNm"), "Prtry", "SEPA")
        if original_iban:
            _sub(
                _sub(_sub(node, "OrgnlDbtrAcct"), "Id"),
                "IBAN",
                fmt.normalize_iban(original_iban, f"{label} original_debtor_iban"),
            )
        if new_debtor_account:
            if flags["smnda_in_account"]:
                account = _sub(_sub(_sub(node, "OrgnlDbtrAcct"), "Id"), "Othr")
                _sub(account, "Id", SMNDA)
            else:
                agent = _sub(_sub(_sub(node, "OrgnlDbtrAgt"), "FinInstnId"), "Othr")
                _sub(agent, "Id", SMNDA)
        if not len(node):
            raise SepaValidationError(
                f"{label} mandate amendment names nothing that changed"
            )

    def _add_purpose(self, parent, transaction):
        purpose = fmt.normalize_code(transaction.get("purpose"), "purpose")
        if purpose:
            _sub(_sub(parent, "Purp"), "Cd", purpose)

    def _add_remittance(self, parent, transaction):
        """Write the remittance information.

        The EPC rulebooks allow either an unstructured line or a structured
        creditor reference, never both; `creditor_reference` wins.
        """
        reference = fmt.sanitize(transaction.get("creditor_reference"), fmt.MAX_ID)
        unstructured = fmt.sanitize(
            transaction.get("remittance_info"), fmt.MAX_REMITTANCE
        )
        if not reference and not unstructured:
            return
        node = _sub(parent, "RmtInf")
        if reference:
            information = _sub(_sub(node, "Strd"), "CdtrRefInf")
            kind = _sub(information, "Tp")
            _sub(_sub(kind, "CdOrPrtry"), "Cd", "SCOR")
            _sub(kind, "Issr", "ISO")
            _sub(information, "Ref", reference)
        else:
            _sub(node, "Ustrd", unstructured)

    # -- reading ----------------------------------------------------------

    def _parse(self, source):
        """Read a pain.001 or pain.008 document.

        `source` is bytes, str or a file-like object. Returns (True, dict) in
        the shape `_build_credit_transfer` and `_build_direct_debit` accept:
        amounts are Decimal, dates are date objects.
        """
        try:
            return True, self._parse_document(_read_xml(source))
        except SepaValidationError as e:
            message = str(e)
        except etree.XMLSyntaxError as e:
            message = f"malformed XML: {e}"
        _logger.warning(
            "sepa_parse_failed",
            extra={"event": "sepa_parse_failed", "error": message},
        )
        return False, message

    def _parse_document(self, root):
        name = etree.QName(root)
        namespace = name.namespace or ""
        if name.localname != "Document" or not namespace.startswith(SCHEMA_PREFIX):
            raise SepaValidationError("not an ISO 20022 Document")
        version = namespace[len(SCHEMA_PREFIX) :]
        body = next((child for child in root if isinstance(child.tag, str)), None)
        document_type = (
            DOCUMENT_TYPE_BY_BODY.get(etree.QName(body).localname)
            if body is not None
            else None
        )
        if document_type is None:
            raise SepaValidationError(
                f"{namespace} is not a SEPA credit transfer or direct debit message"
            )
        family = (
            "pain.001.001." if document_type == CREDIT_TRANSFER else "pain.008.001."
        )
        if not version.startswith(family):
            raise SepaValidationError(
                f"{version} does not match the {document_type} message it carries"
            )
        header = _find(body, "GrpHdr")
        if header is None:
            raise SepaValidationError("document has no GrpHdr")
        return {
            "document_type": document_type,
            "version": version,
            "namespace": namespace,
            "group_header": self._parse_group_header(header),
            "payments": [
                self._parse_payment(node, document_type)
                for node in _children(body, "PmtInf")
            ],
        }

    def _parse_group_header(self, node):
        return _drop_empty(
            {
                "message_id": _text(node, "MsgId"),
                "creation_date_time": _optional(
                    fmt.to_datetime, _text(node, "CreDtTm")
                ),
                "number_of_transactions": _optional(_to_int, _text(node, "NbOfTxs")),
                "control_sum": _optional(fmt.to_decimal, _text(node, "CtrlSum")),
                "initiating_party": self._parse_party(_find(node, "InitgPty")),
            }
        )

    def _parse_payment(self, node, document_type):
        credit_transfer = document_type == CREDIT_TRANSFER
        if credit_transfer:
            party_tag, party_key, transaction_tag = "Dbtr", "debtor", "CdtTrfTxInf"
            ultimate_tag, ultimate_key = "UltmtDbtr", "ultimate_debtor"
            date_tag = "ReqdExctnDt"
        else:
            party_tag, party_key, transaction_tag = "Cdtr", "creditor", "DrctDbtTxInf"
            ultimate_tag, ultimate_key = "UltmtCdtr", "ultimate_creditor"
            date_tag = "ReqdColltnDt"
        batch_booking = _text(node, "BtchBookg")
        payment = {
            "payment_id": _text(node, "PmtInfId"),
            "payment_method": _text(node, "PmtMtd"),
            "batch_booking": batch_booking == "true" if batch_booking else None,
            "number_of_transactions": _optional(_to_int, _text(node, "NbOfTxs")),
            "control_sum": _optional(fmt.to_decimal, _text(node, "CtrlSum")),
            "service_level": _text(node, "PmtTpInf/SvcLvl/Cd"),
            "local_instrument": _text(node, "PmtTpInf/LclInstrm/Cd"),
            "sequence_type": _text(node, "PmtTpInf/SeqTp"),
            "category_purpose": _text(node, "PmtTpInf/CtgyPurp/Cd"),
            "requested_date": _optional(
                fmt.to_date, _requested_date(_find(node, date_tag))
            ),
            "charge_bearer": _text(node, "ChrgBr"),
            "creditor_scheme_id": _text(node, "CdtrSchmeId/Id/PrvtId/Othr/Id"),
            party_key: self._parse_party(
                _find(node, party_tag),
                _find(node, f"{party_tag}Acct"),
                _find(node, f"{party_tag}Agt"),
            ),
            ultimate_key: self._parse_party(_find(node, ultimate_tag)),
            "transactions": [
                self._parse_transaction(child, document_type)
                for child in _children(node, transaction_tag)
            ],
        }
        return _drop_empty(payment)

    def _parse_transaction(self, node, document_type):
        credit_transfer = document_type == CREDIT_TRANSFER
        if credit_transfer:
            party_tag, party_key = "Cdtr", "creditor"
            ultimate_tag, ultimate_key = "UltmtCdtr", "ultimate_creditor"
            amount = _find(node, "Amt/InstdAmt")
        else:
            party_tag, party_key = "Dbtr", "debtor"
            ultimate_tag, ultimate_key = "UltmtDbtr", "ultimate_debtor"
            amount = _find(node, "InstdAmt")
        transaction = {
            "instruction_id": _text(node, "PmtId/InstrId"),
            "end_to_end_id": _text(node, "PmtId/EndToEndId"),
            "amount": _optional(
                fmt.to_decimal, amount.text if amount is not None else ""
            ),
            "currency": amount.get("Ccy") if amount is not None else "",
            party_key: self._parse_party(
                _find(node, party_tag),
                _find(node, f"{party_tag}Acct"),
                _find(node, f"{party_tag}Agt"),
            ),
            ultimate_key: self._parse_party(_find(node, ultimate_tag)),
            "purpose": _text(node, "Purp/Cd"),
            "remittance_info": _text(node, "RmtInf/Ustrd"),
            "creditor_reference": _text(node, "RmtInf/Strd/CdtrRefInf/Ref"),
        }
        if not credit_transfer:
            transaction["mandate"] = self._parse_mandate(
                _find(node, "DrctDbtTx/MndtRltdInf")
            )
        return _drop_empty(transaction)

    def _parse_mandate(self, node):
        if node is None:
            return {}
        amendment_indicator = _text(node, "AmdmntInd")
        return _drop_empty(
            {
                "id": _text(node, "MndtId"),
                "signature_date": _optional(fmt.to_date, _text(node, "DtOfSgntr")),
                "amendment_indicator": (
                    amendment_indicator == "true" if amendment_indicator else None
                ),
                "amendment": self._parse_amendment(_find(node, "AmdmntInfDtls")),
            }
        )

    def _parse_amendment(self, node):
        if node is None:
            return {}
        original_account = _text(node, "OrgnlDbtrAcct/Id/Othr/Id")
        original_agent = _text(node, "OrgnlDbtrAgt/FinInstnId/Othr/Id")
        return _drop_empty(
            {
                "original_mandate_id": _text(node, "OrgnlMndtId"),
                "original_creditor_scheme_id": _text(
                    node, "OrgnlCdtrSchmeId/Id/PrvtId/Othr/Id"
                ),
                "original_creditor_name": _text(node, "OrgnlCdtrSchmeId/Nm"),
                "original_debtor_iban": _text(node, "OrgnlDbtrAcct/Id/IBAN"),
                "same_mandate_new_debtor_account": (
                    True if SMNDA in (original_account, original_agent) else None
                ),
            }
        )

    def _parse_party(self, node, account=None, agent=None):
        party = {}
        if node is not None:
            address = _find(node, "PstlAdr")
            party = {
                "name": _text(node, "Nm"),
                "country": _text(node, "PstlAdr/Ctry"),
                "address_lines": [
                    (line.text or "").strip()
                    for line in (
                        _children(address, "AdrLine") if address is not None else []
                    )
                ],
                "identifier": _text(node, "Id/OrgId/Othr/Id")
                or _text(node, "Id/PrvtId/Othr/Id"),
            }
        if account is not None:
            party["iban"] = _text(account, "Id/IBAN")
        if agent is not None:
            bic = _text(agent, "FinInstnId/BIC") or _text(agent, "FinInstnId/BICFI")
            party["bic"] = bic
        return _drop_empty(party)

    # -- helpers for consumers --------------------------------------------

    def _validate_iban(self, value):
        """Return (True, normalized_iban) or (False, error_message)."""
        try:
            return True, fmt.normalize_iban(value)
        except SepaValidationError as e:
            return False, str(e)

    def _validate_creditor_identifier(self, value):
        """Return (True, normalized_identifier) or (False, error_message)."""
        try:
            return True, fmt.normalize_creditor_identifier(value)
        except SepaValidationError as e:
            return False, str(e)

    def _sanitize_text(self, value, max_length=None):
        """Return `value` mapped onto the SEPA character set."""
        return fmt.sanitize(value, max_length)


def _requested_date(node):
    if node is None:
        return ""
    return _text(node, "Dt") or (node.text or "").strip()


def _to_int(text):
    try:
        return int(text)
    except ValueError as e:
        raise SepaValidationError(f"{text!r} is not a transaction count") from e


def _optional(convert, text):
    return convert(text) if text else None


def _drop_empty(values):
    return {key: value for key, value in values.items() if value or value is False}
