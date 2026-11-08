import frappe
from frappe.core.doctype.communication.communication import (
	add_contact_links_to_communication,
	get_contacts,
	get_email_without_link,
	get_emails,
)

from crm.privacy.inbound import is_erasure_address


class CRMCommunication:
	"""Never auto-create a Contact for a person with an open or finished erasure request.

	Frappe's `set_timeline_links` creates a Contact for every unknown address on the mail
	when the Email Account has `create_contact`. For an erasure address that either makes
	her a new Contact (open request) or hits the do-not-contact block, which Frappe catches
	and logs to an Error Log named after her. Other addresses on the mail are unaffected.
	"""

	def set_timeline_links(self):
		create_contact_enabled = self.email_account and frappe.db.get_value(
			"Email Account", self.email_account, "create_contact"
		)
		if not create_contact_enabled:
			return super().set_timeline_links()

		addresses = get_emails([self.sender, self.recipients, self.cc, self.bcc])
		erasure = {a for a in addresses if is_erasure_address(get_email_without_link(a))}
		if not erasure:
			return super().set_timeline_links()

		# Same as Communication.set_timeline_links, but per address so erasure ones are only looked up.
		if self.sent_or_received == "Received" and self.find_one_by_filters(
			message_id=self.message_id, email_account=self.email_account, sent_or_received="Sent"
		):
			return

		for address in addresses:
			for contact_name in get_contacts([address], auto_create_contact=address not in erasure):
				self.add_link("Contact", contact_name)
				add_contact_links_to_communication(self, contact_name)
