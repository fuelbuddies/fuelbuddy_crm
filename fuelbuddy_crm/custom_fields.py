# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""Custom fields this app owns in code, applied by install.py on install and on every migrate.

These sit on DocTypes outside the fixtures in hooks.py, so the fixtures neither carry nor export them.
Every field here already existed on production, made by hand before it was declared here. Each is
declared exactly as production has it (label, type, options, flags, position), so applying them there
writes nothing; on a site that lacks one, it is created. Change a definition here, never in Customize
Form: the next migrate puts a hand edit back. The behavioural flags (reqd, unique, read_only, hidden,
allow_on_submit, no_copy) are stated even when 0 so that turning one on by hand is put back too.
"""

CUSTOM_FIELDS: dict[str, list[dict]] = {
	"Delivery Note": [
		# The app's invoiced item a Delivery Note delivers: the note's key. The app finds a delivery's
		# note by it (dn_key_columns indexes it; tests/test_dn_key_columns.py expects unique 0, search_index 1).
		{
			"fieldname": "custom_invoiced_item_id",
			"label": "Invoiced Item ID",
			"fieldtype": "Data",
			"insert_after": "custom_is_submitted",
			"reqd": 1,
			"unique": 0,
			"read_only": 0,
			"hidden": 0,
			"allow_on_submit": 0,
			"no_copy": 0,
			"in_global_search": 1,
			"in_list_view": 1,
			"in_preview": 1,
			"in_standard_filter": 1,
			"search_index": 1,
			"translatable": 1,
		},
		# How many times the delivery's note has been amended; the app carries the previous note's
		# version + 1 onto an amendment.
		{
			"fieldname": "custom_version",
			"label": "Version",
			"fieldtype": "Int",
			"insert_after": "custom_invoiced_item_id",
			"reqd": 0,
			"unique": 0,
			"read_only": 1,
			"hidden": 0,
			"allow_on_submit": 0,
			"no_copy": 1,
			"default": "1",
		},
		# The customer's department; the app sets it on a note and corrects it on submitted notes too.
		{
			"fieldname": "custom_department",
			"label": "Department",
			"fieldtype": "Data",
			"insert_after": "custom_gps_location",
			"reqd": 0,
			"unique": 0,
			"read_only": 0,
			"hidden": 0,
			"allow_on_submit": 1,
			"no_copy": 0,
			"in_list_view": 1,
			"translatable": 1,
		},
		# The app's order code.
		{
			"fieldname": "custom_order_code",
			"label": "Order Code",
			"fieldtype": "Data",
			"insert_after": "return_against",
			"reqd": 0,
			"unique": 0,
			"read_only": 0,
			"hidden": 0,
			"allow_on_submit": 0,
			"no_copy": 0,
			"in_global_search": 1,
			"in_list_view": 1,
			"in_preview": 1,
			"in_standard_filter": 1,
			"translatable": 1,
		},
		# The customer's asset the delivery fuelled. Links to Customer Asset, which this app also owns,
		# so the DocType exists before this field is applied.
		{
			"fieldname": "custom_customer_asset",
			"label": "Customer Asset",
			"fieldtype": "Link",
			"options": "Customer Asset",
			"insert_after": "custom_section_break_w5g3d",
			"reqd": 1,
			"unique": 0,
			"read_only": 0,
			"hidden": 0,
			"allow_on_submit": 0,
			"no_copy": 0,
			"in_global_search": 1,
			"in_list_view": 1,
			"in_preview": 1,
			"in_standard_filter": 1,
		},
		# The driver's name, written by the app.
		{
			"fieldname": "custom_driver_name__backend_",
			"label": "Driver Name ( Backend )",
			"fieldtype": "Data",
			"insert_after": "custom_customer_asset",
			"reqd": 0,
			"unique": 0,
			"read_only": 0,
			"hidden": 0,
			"allow_on_submit": 0,
			"no_copy": 0,
			"translatable": 1,
		},
		# Written by the app.
		{
			"fieldname": "custom_gps_location",
			"label": "GPS location",
			"fieldtype": "Data",
			"insert_after": "custom_column_break_m5bkd",
			"reqd": 0,
			"unique": 0,
			"read_only": 0,
			"hidden": 0,
			"allow_on_submit": 0,
			"no_copy": 0,
			"translatable": 1,
		},
		# The Item Group the delivery books as, copied from its Sales Order.
		{
			"fieldname": "custom_transaction_type",
			"label": "Transaction Type",
			"fieldtype": "Link",
			"options": "Item Group",
			"insert_after": "title",
			"reqd": 0,
			"unique": 0,
			"read_only": 0,
			"hidden": 0,
			"allow_on_submit": 0,
			"no_copy": 0,
			"in_global_search": 1,
			"in_preview": 1,
			"in_standard_filter": 1,
		},
	],
	"Sales Order Item": [
		# The quantity draft Delivery Notes hold on the row. The app's allocator subtracts it from what
		# the row has left (patches/move_draft_dn_reservation_to_app keeps it current).
		{
			"fieldname": "custom_delivery_note_qty_in_draft",
			"label": "Delivery Note Qty In Draft",
			"fieldtype": "Float",
			"insert_after": "picked_qty",
			"reqd": 0,
			"unique": 0,
			"read_only": 0,
			"hidden": 0,
			"allow_on_submit": 1,
			"no_copy": 0,
		},
	],
	"Address": [
		# A shipping address's billing address; the app bills a delivery to it.
		{
			"fieldname": "custom_billing_address",
			"label": "Billing Address",
			"fieldtype": "Link",
			"options": "Address",
			"insert_after": "custom_longitude",
			"reqd": 0,
			"unique": 0,
			"read_only": 0,
			"hidden": 0,
			"allow_on_submit": 0,
			"no_copy": 0,
		},
	],
	"Issue": [
		# The invoiced item a delivery's Issue is about; the app looks for an open Issue by it before
		# raising another.
		{
			"fieldname": "custom_invoice_item_id",
			"label": "Invoice Item ID",
			"fieldtype": "Data",
			"insert_after": "priority",
			"reqd": 0,
			"unique": 0,
			"read_only": 0,
			"hidden": 0,
			"allow_on_submit": 0,
			"no_copy": 0,
			"in_global_search": 1,
			"in_list_view": 1,
			"in_preview": 1,
			"in_standard_filter": 1,
			"translatable": 1,
		},
		# The app's order code.
		{
			"fieldname": "custom_order_code",
			"label": "Order Code",
			"fieldtype": "Data",
			"insert_after": "custom_invoice_item_id",
			"reqd": 0,
			"unique": 0,
			"read_only": 0,
			"hidden": 0,
			"allow_on_submit": 0,
			"no_copy": 0,
			"translatable": 1,
		},
	],
	"Asset Category": [
		# The app's asset type id for the category. Customer Asset (this app) fetches its asset_type_id
		# from it when an asset has a category; declared here so that fetch always has a field to read.
		{
			"fieldname": "custom_hasura_asset_type_id",
			"label": "Hasura Asset Type Id",
			"fieldtype": "Data",
			"insert_after": "column_break_3",
			"reqd": 0,
			"unique": 0,
			"read_only": 0,
			"hidden": 0,
			"allow_on_submit": 0,
			"no_copy": 0,
			"translatable": 1,
		},
	],
}
