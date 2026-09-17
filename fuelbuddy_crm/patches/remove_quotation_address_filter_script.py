# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""Delete the "Quotation Filtering On Fields" Client Script.

Its link query on `customer_address` filtered on the literal string 'party_name' as
link_doctype and on the Quotation's OWN name as link_name, so the Billing Address
dropdown returned zero rows -- invisible when the customer had a single address
(ERPNext auto-fills it), fatal when it had several. The working query now lives in
fuelbuddy_crm/public/js/quotation.js (loaded via hooks.doctype_js), and the script is
gone from the app's fixtures so sync-fixtures won't re-create it."""

import frappe

_SCRIPT = "Quotation Filtering On Fields"


def execute():
	if frappe.db.exists("Client Script", _SCRIPT):
		frappe.delete_doc("Client Script", _SCRIPT, ignore_permissions=True, force=True)
