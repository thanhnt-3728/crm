# Frappe v16 / whatsapp API verification (researcher, 2026-11-05)

Read from `frappe/frappe@version-16` and `frappe/whatsapp@develop` (raw GitHub). Line numbers as fetched;
the installed release may differ slightly. UNVERIFIED items must be confirmed on the bench in phase 03 step 1.

| # | Fact | Source |
|---|---|---|
| 1 | `delete_doc(..., ignore_on_trash=False, ignore_missing=True, delete_permanently=False)`; `delete_permanently=True` skips `add_to_deleted_document` (which stores full `doc.as_json()`) | `model/delete_doc.py` L24-35, L224-248 |
| 1 | File physical removal on delete: **UNVERIFIED** (`File.on_trash` not read) | — |
| 2 | `save_version()` returns early on `flags.ignore_version`, `doctype == "Version"`, no `track_changes` | `model/document.py` L1860-1868 |
| 2 | In tests `_save` sets `ignore_version = frappe.in_test` → **no Version rows in tests by default** | `document.py` L797-814 |
| 2 | `db_set(fieldname, value, update_modified=True, notify=False, commit=False)` fires `before_change`/`on_change`, no Version, no global search. `frappe.db.set_value` = raw SQL, no hooks (internals UNVERIFIED) | `document.py` L1787-1840 |
| 3 | `delete_for_document(doc)` deletes `__global_search` rows; `update_global_search(doc)` re-queues but writes only if content non-empty → must delete explicitly first | `utils/global_search.py` L242-286, L470-476 |
| 3 | Indexed: Contact first_name/email_id/user; Address city/country; Communication subject/sender | doctype JSONs |
| 4 | v16 `_comments` stores `{name}` only; older rows may still carry text | `core/doctype/comment/comment.py` L213-275 |
| 5 | Contact, Address: no `track_changes`. Contact Email `email_id`; Contact Phone `phone`; Dynamic Link `link_title` | contacts JSONs |
| 6 | Communication `track_changes=1`; fields incl. `phone_no`, `sender_full_name`, `timeline_links` (Communication Link `link_title`). Comment `track_changes=1`; `comment_email`, `comment_by`, `ip_address` | communication/comment JSON |
| 6 | Version diff skips Text Editor/Code/HTML/Markdown fields (content, recipients, cc, bcc not in diffs) | `version.py` L118 |
| 7 | Email Queue (`track_changes=1`): `message` plain MIME; child Email Queue Recipient `recipient`. Notification Log: title, subject, description, email_content | email_queue.json/.py |
| 8 | Deleted Document: `deleted_doctype`, `deleted_name`, `data` (full JSON) | deleted_document.json |
| 9 | Version `data`: `changed [[f,old,new]]`, `added/removed [[table,{row}]]`, `row_changed [[table, idx, row_name, [[f,old,new]]]]` | `version.py` L102-221 |
| 10 | WA Profile `autoname=hash`; phone_number, wa_id, profile_name, links. WA Message submittable, `to`→WA Profile, `from` Data (phone), message, media_*, attach, template params, interactive_*. WA Log stores raw `request_data`/`response_data` JSON incl. phone + text, no FK | whatsapp doctype JSONs, `webhook.py` L73,129-134,238 |
| 11 | `IntegrationTestCase` rolls back per **class**, not per test → keep `tearDown: frappe.db.rollback()` as existing tests do | `tests/classes/integration_test_case.py` L66-72, L195 |

Consequences for the plan: tests that prove "no new Version rows" must re-enable versioning
(`frappe.in_test` patched to False around the run) or the test passes hollowly; Communication, Comment,
Email Queue and WA Log Versions must be purged too; WA Log/Error Log found by text scan only.
