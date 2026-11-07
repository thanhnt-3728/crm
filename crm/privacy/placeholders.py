# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Text that replaces erased data, tagged with the request number so it can be traced (design 3, 5.6).

`request` is a request number such as "PDR-0001" or any document/dict carrying it as `name`.
Pure: no DB. Deliberately not translated, because the text is written into records permanently.
"""


def _number(request) -> str:
	return request if isinstance(request, str) else request.name


def erased_person(request) -> str:
	return f"Erased person {_number(request)}"


def erased_content(request) -> str:
	return f"Content erased {_number(request)}"


def erased_file(request) -> str:
	return f"File erased {_number(request)}"
