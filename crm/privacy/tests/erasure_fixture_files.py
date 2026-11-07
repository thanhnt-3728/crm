# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Files of the Marisol scenario: they write bytes to disk, which a rollback leaves behind (phase 05 step 1)."""

import io

import frappe
from PIL import Image

BYTES: list[str] = []  # where the fixture's files were written; a rollback leaves them on disk


def file_doc(doctype: str, name: str, file_name: str, private: int = 1, content=None):
	doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"content": content or f"bytes of {file_name}",
			"is_private": private,
			"attached_to_doctype": doctype,
			"attached_to_name": name,
		}
	).insert(ignore_permissions=True)
	BYTES.append(doc.get_full_path())
	return doc


def jpeg() -> bytes:
	buffer = io.BytesIO()
	Image.new("RGB", (1, 1)).save(buffer, "JPEG")
	return buffer.getvalue()
