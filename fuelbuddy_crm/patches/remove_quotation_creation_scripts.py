# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""The Opportunity -> Quotation creation flow moved into the app (a whitelisted
Python method ``fuelbuddy_crm.quotation_link.create_quotation_from_opportunity`` plus
the ``Opportunity`` doctype_js form script). Delete the now-superseded DB scripts so
they don't shadow or duplicate the app logic. Both are also removed from the app's
fixtures, so they won't be re-created on sync-fixtures."""

import frappe

_SCRIPTS = (
	("Server Script", "Opportunity Send for Quotation"),
	("Client Script", "Create Finance Dosier"),
)


def execute():
	for doctype, name in _SCRIPTS:
		if frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
