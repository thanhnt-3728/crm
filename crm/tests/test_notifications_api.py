from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.notifications import (
	NOTIFICATIONS_PAGE_LENGTH,
	get_notifications,
	get_unread_count,
	mark_as_read,
)

USER1 = "crm.user1@example.com"
USER2 = "crm.user2@example.com"
SENDER = "crm.admin@example.com"


def make_notification(to_user, **kwargs):
	doc = frappe.get_doc(
		{
			"doctype": "CRM Notification",
			"from_user": SENDER,
			"to_user": to_user,
			"type": "Mention",
			"message": "mentioned you",
			**kwargs,
		}
	)
	doc.flags.ignore_links = True
	return doc.insert(ignore_permissions=True)


class TestNotificationsAPI(IntegrationTestCase):
	def setUp(self):
		frappe.db.delete("CRM Notification", {"to_user": ["in", [USER1, USER2]]})

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_list_is_capped_and_newest_first(self):
		for _ in range(NOTIFICATIONS_PAGE_LENGTH + 5):
			make_notification(USER1)

		frappe.set_user(USER1)
		notifications = get_notifications()

		self.assertEqual(len(notifications), NOTIFICATIONS_PAGE_LENGTH)
		creations = [n["creation"] for n in notifications]
		self.assertEqual(creations, sorted(creations, reverse=True))

	def test_list_shows_only_own_notifications_with_sender_name(self):
		make_notification(USER1)
		make_notification(USER2)

		frappe.set_user(USER1)
		notifications = get_notifications()

		self.assertEqual({n["to_user"] for n in notifications}, {USER1})
		self.assertEqual(
			notifications[0]["from_user"]["full_name"], frappe.db.get_value("User", SENDER, "full_name")
		)

	def test_unread_count_includes_notifications_past_the_page(self):
		for _ in range(NOTIFICATIONS_PAGE_LENGTH + 5):
			make_notification(USER1)
		make_notification(USER1, read=1)

		frappe.set_user(USER1)
		self.assertEqual(get_unread_count(), NOTIFICATIONS_PAGE_LENGTH + 5)

	def test_mark_all_as_read_touches_only_own_and_sends_one_event(self):
		for _ in range(3):
			make_notification(USER1)
		make_notification(USER2)

		frappe.set_user(USER1)
		with patch("crm.api.notifications.frappe.publish_realtime") as publish:
			mark_as_read()

		self.assertEqual(get_unread_count(), 0)
		self.assertEqual(frappe.db.count("CRM Notification", {"to_user": USER2, "read": 0}), 1)
		publish.assert_called_once_with("crm_notification", user=USER1, after_commit=True)

	def test_mark_one_doc_as_read(self):
		make_notification(USER1, notification_type_doctype="Comment", notification_type_doc="COMMENT-1")
		make_notification(USER1, notification_type_doctype="Comment", notification_type_doc="COMMENT-2")

		frappe.set_user(USER1)
		mark_as_read("COMMENT-1")

		unread = frappe.get_all(
			"CRM Notification", {"to_user": USER1, "read": 0}, pluck="notification_type_doc"
		)
		self.assertEqual(unread, ["COMMENT-2"])

	def test_mark_unknown_doc_as_read_changes_nothing(self):
		make_notification(USER1)

		frappe.set_user(USER1)
		mark_as_read("NO-SUCH-COMMENT")

		self.assertEqual(get_unread_count(), 1)

	def test_routes_follow_the_reference_doctype(self):
		make_notification(USER1, reference_doctype="CRM Lead", reference_name="CRM-LEAD-1")
		make_notification(USER1, reference_doctype="CRM Deal", reference_name="CRM-DEAL-1")
		make_notification(
			USER1, type="Privacy", reference_doctype="CRM Erasure Request", reference_name="PDR-0001"
		)

		frappe.set_user(USER1)
		routes = {n["reference_name"]: n["route_name"] for n in get_notifications()}

		self.assertEqual(routes, {"CRM-LEAD-1": "Lead", "CRM-DEAL-1": "Deal", "PDR-0001": "ErasureRequest"})

	def test_no_reference_means_no_route(self):
		make_notification(USER1, type="Privacy")

		frappe.set_user(USER1)
		(notification,) = get_notifications()

		self.assertIsNone(notification["route_name"])
