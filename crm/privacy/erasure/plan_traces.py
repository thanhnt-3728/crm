# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Traces of her that are not records: events she is invited to, the browser's route history, saved list filters,
and who holds the recordings of her calls (review M4, L6). Read-only; whole-value matching (RT-4)."""

from urllib.parse import quote, unquote

import frappe

from crm.privacy.erasure.plan_queries import like_candidates, present
from crm.privacy.erasure.text_mentions import mentions_identifier, prefilter_terms
from crm.privacy.erasure.value_matcher import Identifiers, like_literal

KNOWN_PROVIDERS = ("Twilio", "Exotel")


def events_of(participants: list[str]) -> list[str]:
	"""The events that her participant rows belong to."""
	if not participants:
		return []
	Row = frappe.qb.DocType("Event Participants")
	query = (
		frappe.qb.from_(Row)
		.select(Row.parent)
		.where((Row.parenttype == "Event") & Row.name.isin(participants))
	)
	return sorted(set(query.run(pluck=True)))


def route_history(docnames: list[str]) -> list[str]:
	"""Route History rows whose route has one of these docnames as a path segment, plain or URL-encoded
	(`app/contact/Marisol%20Vega`): contact and address docnames carry her name."""
	if not (docnames and present("Route History")):
		return []
	wanted = {name.lower() for name in docnames}
	terms = sorted({*docnames, *(quote(name) for name in docnames)})
	found = []
	for row in like_candidates("Route History", ["route"], terms):
		if any(unquote(part).lower() in wanted for part in (row.route or "").split("/")):
			found.append(row.name)
	return sorted(found)


def user_settings(ids: Identifiers) -> list[str]:
	"""Saved list views (`__UserSettings`) with one of her identifiers in a filter, as `user::doctype`."""
	found = set()
	for term in prefilter_terms(ids):
		rows = frappe.db.sql(
			"select `user`, `doctype`, `data` from `__UserSettings` where `data` like %s",
			f"%{like_literal(term)}%",
		)
		found |= {f"{user}::{doctype}" for user, doctype, data in rows if mentions_identifier(data, ids)}
	return sorted(found)


def recording_providers(calls: list[str]) -> list[str]:
	"""Who holds the recordings of the target calls: the provider of each call that has one. A number with no
	known provider is taken for Twilio, as before."""
	if not calls:
		return []
	rows = frappe.get_all(
		"CRM Call Log", {"name": ["in", calls], "recording_url": ["is", "set"]}, ["telephony_medium"]
	)
	return sorted({r.telephony_medium if r.telephony_medium in KNOWN_PROVIDERS else "Twilio" for r in rows})
