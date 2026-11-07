# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Which bytes the post-commit deletion may touch (review M3): site-local /files/ and /private/files/ URLs only."""

import os

import frappe
from frappe.tests import IntegrationTestCase

from crm.privacy.erasure.file_bytes import delete_bytes, path_of

NAME = "file-bytes-test-report.txt"


class TestFileBytes(IntegrationTestCase):
	def make(self, private: bool, name: str = NAME) -> str:
		path = frappe.get_site_path("private" if private else "public", "files", name)
		with open(path, "w") as handle:
			handle.write("bytes")
		self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
		return path

	def test_an_external_url_is_never_mapped_to_a_local_file(self):
		path = self.make(private=False)
		for url in (
			f"https://cdn.example.com/files/{NAME}",
			f"//cdn.example.com/files/{NAME}",
			f"ftp://h/files/{NAME}",
		):
			self.assertIsNone(path_of(url, 0), url)
			delete_bytes([[url, 0]])
			self.assertTrue(os.path.exists(path), url)

	def test_only_the_two_site_folders_and_no_way_out_of_them(self):
		for url in (
			"/files/../site_config.json",
			"/private/files/../../site_config.json",
			"/files/",
			"/other/files/x",
			"files/x",
			"",
			None,
		):
			self.assertIsNone(path_of(url, 0), url)

	def test_the_folder_follows_the_url_prefix_not_the_private_flag(self):
		private, public = self.make(private=True), self.make(private=False, name="file-bytes-test-public.txt")
		delete_bytes([[f"/private/files/{NAME}", 0], ["/files/file-bytes-test-public.txt", 1]])
		self.assertFalse(os.path.exists(private))
		self.assertFalse(os.path.exists(public))

	def test_the_local_urls_resolve_under_the_files_folders(self):
		self.assertEqual(
			path_of("/files/a.txt", 1), os.path.realpath(frappe.get_site_path("public", "files", "a.txt"))
		)
		self.assertEqual(
			path_of("/private/files/a.txt", 0),
			os.path.realpath(frappe.get_site_path("private", "files", "a.txt")),
		)
