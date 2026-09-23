# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""Delivery Note -> Sales Invoice link fields (fuelbuddy_crm.dn_invoice_link).

Creates Delivery Note.custom_sales_invoice / custom_sales_invoice_qty (plus their section and
column break), indexes the link column -- every invoice save clears its own DNs by it, and
unindexed that is a full scan of the DN table -- and removes the child-table prototype this
replaced (app fuelbuddy_dn_invoice_link: doctype "Delivery Note Invoice Allocation" and the
Delivery Note table field pointing at it), which was only ever installed on local sites."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from fuelbuddy_crm.dn_invoice_link import LINK_FIELD, QTY_FIELD

CUSTOM_FIELDS = {
	"Delivery Note": [
		{
			"fieldname": "custom_sales_invoices_section",
			"fieldtype": "Section Break",
			"label": "Sales Invoices",
			"insert_after": "custom_total_quantity_in_ig",
			"collapsible": 1,
		},
		{
			"fieldname": LINK_FIELD,
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"label": "Sales Invoice",
			"insert_after": "custom_sales_invoices_section",
			"allow_on_submit": 1,
			"read_only": 1,
			"no_copy": 1,
			"in_standard_filter": 1,
			"search_index": 1,
			"description": "Set by Sales Invoice save: the invoice that billed this Delivery Note.",
		},
		{
			"fieldname": "custom_column_break_mnbzw",
			"fieldtype": "Column Break",
			"insert_after": LINK_FIELD,
		},
		{
			"fieldname": QTY_FIELD,
			"fieldtype": "Float",
			"label": "Sales Invoice Qty",
			"insert_after": "custom_column_break_mnbzw",
			"allow_on_submit": 1,
			"read_only": 1,
			"no_copy": 1,
			"description": "Litres of this Delivery Note billed on that invoice (stock UOM).",
		},
	],
}

OLD_TABLE_FIELD = "custom_invoice_allocations"
OLD_DOCTYPE = "Delivery Note Invoice Allocation"


def execute():
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	frappe.db.add_index("Delivery Note", [LINK_FIELD])
	if frappe.db.exists("Custom Field", {"dt": "Delivery Note", "fieldname": OLD_TABLE_FIELD}):
		frappe.delete_doc("Custom Field", f"Delivery Note-{OLD_TABLE_FIELD}", force=True, ignore_permissions=True)
	if frappe.db.exists("DocType", OLD_DOCTYPE):
		frappe.delete_doc("DocType", OLD_DOCTYPE, force=True, ignore_permissions=True)
	frappe.db.sql_ddl(f"drop table if exists `tab{OLD_DOCTYPE}`")
