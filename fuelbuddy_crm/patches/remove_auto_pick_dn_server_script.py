# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""The "Auto Pick of DN at Sales Invoice and Update of Qty" Server Script (manual
period invoices: roll DN quantities in a date range up onto the SO lines) moved into
the app as auto_invoicing.rebuild_lines_from_dn_range, where it shares the
per-delivery Force Majeure split with the scheduler (IDEV-3129). Delete the DB script
so it cannot run after the hook and undo the split."""

import frappe

SCRIPT = "Auto Pick of DN at Sales Invoice and Update of Qty"


def execute():
	if frappe.db.exists("Server Script", SCRIPT):
		frappe.delete_doc("Server Script", SCRIPT, ignore_permissions=True, force=True)
