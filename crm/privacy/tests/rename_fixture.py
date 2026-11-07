# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Fixture of the `rename_doc` spike (phase 05 step 0): a Contact and an Address with a reference of every kind.

Fixtures are committed first (a rollback must have something to go back to), so `clean_up` deletes what they made.
"""

from unittest.mock import patch

import frappe
from frappe.model.dynamic_links import get_dynamic_link_map
from frappe.model.rename_doc import get_link_fields, rename_doc
from frappe.tests import IntegrationTestCase

from crm.privacy.tests.make_test_user import make_deal

PLACEHOLDERS = {"Contact": "Erased person PDR-9001", "Address": "Erased person PDR-9001-address"}


def references(doctype: str, names: list[str]) -> dict:
	"""Rows that point at `names` through every Link field and every Dynamic Link field of the doctype,
	plus the child rows parented to them and the Version/File rows that carry the docname."""
	found = {}
	for field in get_link_fields(doctype):
		if not field["issingle"]:
			rows = frappe.get_all(field["parent"], {field["fieldname"]: ["in", names]}, pluck="name")
			found[(field["parent"], field["fieldname"])] = sorted(rows)
	for field in get_dynamic_link_map().get(doctype, []):
		if not frappe.get_meta(field.parent).issingle:
			filters = {field.options: doctype, field.fieldname: ["in", names]}
			found[(field.parent, field.fieldname)] = sorted(
				frappe.get_all(field.parent, filters, pluck="name")
			)
	found[("Version", "docname")] = sorted(
		frappe.get_all("Version", {"ref_doctype": doctype, "docname": ["in", names]}, pluck="name")
	)
	found[("File", "attached_to_name")] = sorted(
		frappe.get_all(
			"File", {"attached_to_doctype": doctype, "attached_to_name": ["in", names]}, pluck="name"
		)
	)
	return {key: rows for key, rows in found.items() if rows}


class RenameFixture(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# The fixture commits, which flushes every enqueue the inserts and deletes registered; no worker runs in
		# the test bench, so real jobs would pile up until the queue refuses more (QueueOverloaded).
		enqueue = patch("frappe.enqueue")
		enqueue.start()
		self.addCleanup(enqueue.stop)
		self.names = {}
		contact = frappe.get_doc(
			{"doctype": "Contact", "first_name": "Spike", "last_name": "Person", "designation": "A"}
		)
		contact.append("email_ids", {"email_id": "spike.person@example.com", "is_primary": 1})
		contact.append("phone_nos", {"phone": "+15305550188", "is_primary_mobile_no": 1})
		contact.insert()
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "Spike Person",
				"address_type": "Billing",
				"address_line1": "1 Spike Way",
				"city": "Chico",
				"country": "United States",
				"links": [{"link_doctype": "Contact", "link_name": contact.name}],
			}
		)
		address.insert()
		contact.address = address.name
		contact.append("links", {"link_doctype": "Address", "link_name": address.name})
		contact.designation = "B"
		contact.save()
		frappe.get_doc(  # Contact keeps no history of its own, but the CRM writes Versions with a contact's data
			{"doctype": "Version", "ref_doctype": "Contact", "docname": contact.name, "data": "{}"}
		).insert()
		contact.add_comment("Comment", "a comment on the contact")
		frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "call back",
				"reference_type": "Contact",
				"reference_name": contact.name,
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "spike.txt",
				"content": "spike",
				"is_private": 1,
				"attached_to_doctype": "Contact",
				"attached_to_name": contact.name,
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"sent_or_received": "Received",
				"subject": "hello",
				"content": "hello",
				"sender": "spike.person@example.com",
				"reference_doctype": "Contact",
				"reference_name": contact.name,
				"timeline_links": [{"link_doctype": "Contact", "link_name": contact.name}],
			}
		).insert()
		self.deal = make_deal([contact.name], status="Negotiation")
		self.names = {"Contact": contact.name, "Address": address.name}
		frappe.db.commit()  # the rollback under test must have committed state to return to
		self.before = self.snapshot()
		self.addCleanup(self.clean_up)

	def snapshot(self) -> dict:
		current = [self.names["Contact"], PLACEHOLDERS["Contact"]]
		return {
			"contact": references("Contact", current),
			"address": references("Address", [self.names["Address"], PLACEHOLDERS["Address"]]),
			"exists": [
				bool(frappe.db.exists(dt, n)) for dt in self.names for n in (self.names[dt], PLACEHOLDERS[dt])
			],
		}

	def clean_up(self):
		frappe.db.rollback()
		mine = [*self.names.values(), *PLACEHOLDERS.values()]
		for name in frappe.get_all("File", {"attached_to_name": ["in", mine]}, pluck="name"):
			frappe.delete_doc("File", name, force=True, ignore_permissions=True)  # also removes the bytes
		frappe.db.delete("Communication", {"reference_name": ["in", mine]})
		frappe.db.delete("ToDo", {"reference_name": ["in", mine]})
		frappe.db.delete("Comment", {"reference_name": ["in", mine]})
		frappe.db.delete("Version", {"docname": ["in", mine]})
		frappe.delete_doc("CRM Deal", self.deal, force=True, ignore_permissions=True)
		for doctype, name in self.names.items():
			for candidate in (name, PLACEHOLDERS[doctype]):
				if frappe.db.exists(doctype, candidate):
					frappe.delete_doc(doctype, candidate, force=True, ignore_permissions=True)
		frappe.db.commit()

	def rename_both(self):
		"""What the executor's rename step does: Contact and Address to their placeholders, no side jobs."""
		for doctype in ("Contact", "Address"):
			rename_doc(
				doctype,
				self.names[doctype],
				PLACEHOLDERS[doctype],
				force=True,
				ignore_permissions=True,
				show_alert=False,
				rebuild_search=False,
			)
