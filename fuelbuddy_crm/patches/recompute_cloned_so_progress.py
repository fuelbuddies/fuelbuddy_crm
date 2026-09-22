# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""Contract Sales Orders cloned month-to-month before f00f0d8 went through
frappe.copy_doc with its default (no_copy fields copied too), so each new month was
born with the template's per_delivered / per_billed / delivery_status /
billing_status / status. Rows self-heal on the next DN or SI submit; the header only
does when something is submitted against THAT SO, so some still carry the copied
numbers and a few were born "Completed" / "To Bill", which auto-invoicing skips.
Recompute every submitted contract SO's header from its own rows using ERPNext's
percent + status logic (the same code a DN / SI submit runs). Idempotent."""

import frappe


def execute():
	# ponytail: borrow the DN/SI status_updater rules instead of retyping the SQL
	dn = frappe.new_doc("Delivery Note")
	si = frappe.new_doc("Sales Invoice")
	rules = [a for a in dn.status_updater + si.status_updater if a.get("target_parent_dt") == "Sales Order"]
	sos = frappe.get_all(
		"Sales Order", filters={"docstatus": 1, "custom_quotation": ["is", "set"]}, pluck="name"
	)
	for so in sos:
		for args in rules:
			dn._update_percent_field(dict(args, name=so))
