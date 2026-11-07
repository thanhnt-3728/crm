# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The erasure plan: everything one approved request will change, built once and shared by the approval screen
and the job (design 5.6), so the screen cannot promise what the job does not do.

`targets` maps each kind to the sorted docnames the job will touch. Its hash, with the non-excluded identifiers,
is stored at approval and checked again by the job before anything is erased (RT-1).
"""

import hashlib
import json
from dataclasses import dataclass, field

import frappe

from crm.privacy.erasure.value_matcher import Identifiers

RECORDS = ("leads", "deals_on", "deals_copy", "deals_removed", "contacts", "addresses")
ACTIVITIES = ("communications", "call_logs", "notes", "tasks", "comments", "todos", "files")
HISTORY = ("versions", "deleted_documents")
MISC = (
	"crm_notifications",
	"notification_logs",
	"email_queues",
	"wa_messages",
	"wa_profiles",
	"event_participants",
	"failed_sync_logs",
	"enrichment_changes",
	"activity_logs",
	"unhandled_emails",
	"events",
	"route_history",
	"user_settings",
)
# Rows the privacy module itself wrote about this request (the On Hold owner notices): deleted, not scrubbed (RT-10).
NOTICES = ("hold_notifications", "hold_notification_logs", "hold_emails")
KINDS = RECORDS + ACTIVITIES + HISTORY + MISC + NOTICES


class ErasureHoldError(frappe.ValidationError):
	"""A deal she is still on is open: the request belongs On Hold, not in the job (RT-2)."""


@dataclass
class ErasurePlan:
	request: str
	identifiers: Identifiers
	targets: dict[str, list[str]] = field(default_factory=lambda: {kind: [] for kind in KINDS})
	personal_fields: dict[str, list[str]] = field(
		default_factory=dict
	)  # doctype -> fieldnames, from settings
	her_values: dict[str, list[str]] = field(
		default_factory=dict
	)  # fieldname -> her values on confirmed records
	gone: list[tuple[str, str]] = field(
		default_factory=list
	)  # confirmed records deleted since: (doctype, name)
	recording_providers: list[str] = field(
		default_factory=list
	)  # providers of the recordings on target call logs: one checklist item each
	retention_months: int = 0  # contract retention at approval: what the retained contracts will last
	data_imports: int = 0  # Data Imports of leads, deals or contacts: the checklist item (V1)
	field_gaps: list[dict] = field(
		default_factory=list
	)  # custom fields holding text that are not on the list
	open_deals: list[str] = field(default_factory=list)  # deals she is on that are still open (RT-2)
	shared_addresses: list[str] = field(
		default_factory=list
	)  # addresses also linked to someone else: left alone

	@property
	def recordings(self) -> bool:
		return bool(self.recording_providers)

	def hash(self) -> str:
		"""SHA-256 of the canonical, sorted targets, the shared addresses [I3], the non-excluded identifiers, the
		personal-fields list and the retention months: everything that decides what the job does."""
		canonical = {
			"identifiers": {
				"emails": sorted(self.identifiers.emails),
				"phones": sorted(self.identifiers.phones),
			},
			"targets": {kind: sorted(self.targets.get(kind, [])) for kind in sorted(KINDS)},
			"shared_addresses": sorted(self.shared_addresses),
			"personal_fields": {k: sorted(v) for k, v in sorted(self.personal_fields.items())},
			"retention_months": self.retention_months,
		}
		return hashlib.sha256(
			json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
		).hexdigest()

	def docs(self) -> list[tuple[str, str]]:
		"""(doctype, name) of every row whose change history and deleted copy are in scope."""
		by_kind = (
			("CRM Lead", "leads"),
			("CRM Deal", "deals_on"),
			("CRM Deal", "deals_copy"),
			("CRM Deal", "deals_removed"),
			("Contact", "contacts"),
			("Address", "addresses"),
			("Communication", "communications"),
			("FCRM Note", "notes"),
			("CRM Task", "tasks"),
			("ToDo", "todos"),
			("Comment", "comments"),
			("File", "files"),
			("Email Queue", "email_queues"),
			("Event", "events"),
		)
		return [(doctype, name) for doctype, kind in by_kind for name in self.targets[kind]]
