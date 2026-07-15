# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""The CRM Server Scripts moved into the app: "Item Creation at Opportunity Level"
-> validations.sync_opportunity_value_item, "Quotation Status to Opportunity" ->
quotation_link.sync_status_to_opportunity. "Calculation" and "Opportunity Discount
Writeback" were already superseded by validations.apply_opportunity_calculations
and discount_sync.writeback_opportunity_discount; "Lead" and "POC" were disabled
legacy scripts. Delete them all so nothing shadows or duplicates the app logic;
they are also gone from the app's fixtures, so sync-fixtures won't re-create them."""

import frappe

_SCRIPTS = (
	"Lead",
	"POC",
	"Item Creation at Opportunity Level",
	"Calculation",
	"Opportunity Discount Writeback",
	"Quotation Status to Opportunity",
)


def execute():
	for name in _SCRIPTS:
		if frappe.db.exists("Server Script", name):
			frappe.delete_doc("Server Script", name, ignore_permissions=True, force=True)
