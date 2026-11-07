# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Replace her identifiers inside a JSON text, wherever they are a whole value; or every text value of a payload that
is hers (a failed lead sync: her name sits beside her email). Pure: no database."""

import frappe

from crm.privacy.erasure.value_matcher import Identifiers, holds_identifier


def _blank(node, hers, placeholder: str):
	"""`node` with each string that `hers` accepts replaced by `placeholder`."""
	if isinstance(node, dict):
		return {key: _blank(value, hers, placeholder) for key, value in node.items()}
	if isinstance(node, list):
		return [_blank(value, hers, placeholder) for value in node]
	return placeholder if isinstance(node, str) and hers(node) else node


def _rewrite(text: str | None, hers, placeholder: str) -> str | None:
	try:
		document = frappe.parse_json(text or "")
	except Exception:
		return text
	if not isinstance(document, dict | list):
		return text
	return frappe.as_json(_blank(document, hers, placeholder))


def blank_identifiers(text: str | None, ids: Identifiers, placeholder: str) -> str | None:
	"""`text` (JSON) with each string value that is one of her identifiers, or an address list holding one,
	replaced by `placeholder`. Text that is not JSON is returned as it was."""
	return _rewrite(text, lambda value: holds_identifier(value, ids), placeholder)


def blank_text_values(text: str | None, placeholder: str) -> str | None:
	"""`text` (JSON) with every non-empty string value replaced by `placeholder`; keys, numbers and flags stay.
	Text that is not JSON is returned as it was."""
	return _rewrite(text, lambda value: bool(value.strip()), placeholder)
