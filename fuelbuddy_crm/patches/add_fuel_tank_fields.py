# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""From Tank / To Tank Links on Delivery Note, Purchase Receipt and Stock Entry, added online like add_app_op_key."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field, create_custom_fields

LOCK_WAIT_SECONDS = 5
DESCRIPTION = "The FuelBuddy tank. A document that touches one tank names it in both From Tank and To Tank."

# erp-functions LANE_ERP_FIELDS.FROM_TANK / TO_TANK name these fields.
CUSTOM_FIELDS = {
	doctype: [
		{
			"fieldname": "custom_from_tank",
			"fieldtype": "Link",
			"options": "Fuel Tank",
			"label": "From Tank",
			"insert_after": anchor,
			"description": DESCRIPTION,
		},
		{
			"fieldname": "custom_to_tank",
			"fieldtype": "Link",
			"options": "Fuel Tank",
			"label": "To Tank",
			"insert_after": "custom_from_tank",
			"description": DESCRIPTION,
		},
	]
	for doctype, anchor in (
		("Delivery Note", "set_warehouse"),
		("Purchase Receipt", "set_warehouse"),
		("Stock Entry", "to_warehouse"),
	)
}


def execute():
	if frappe.db.db_type != "mariadb":
		create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
		return

	previous = frappe.db.sql("select @@session.lock_wait_timeout")[0][0]
	frappe.db.sql("set session lock_wait_timeout = %s", LOCK_WAIT_SECONDS)
	try:
		for doctype, fields in CUSTOM_FIELDS.items():
			_add_columns(f"tab{doctype}", [field["fieldname"] for field in fields])
	finally:
		frappe.db.sql("set session lock_wait_timeout = %s", previous)

	_register_fields()


def _add_columns(table, columns):
	missing = [column for column in columns if not _has_column(table, column)]
	if not missing:
		return
	clauses = ", ".join(
		f"add column if not exists `{column}` varchar({frappe.db.VARCHAR_LEN})" for column in missing
	)
	statement = f"alter table `{table}` {clauses}, algorithm=instant"
	try:
		frappe.db.sql_ddl(statement)
	except Exception:
		print(
			f"add_fuel_tank_fields: {statement!r} failed and changed nothing (lock wait capped at "
			f"{LOCK_WAIT_SECONDS}s). The patch is safe to re-run: run bench migrate again."
		)
		raise
	finally:
		frappe.cache.hdel("table_columns", table)


def _has_column(table, column):
	return bool(
		frappe.db.sql(
			"""select 1 from information_schema.columns
			where table_schema = database() and table_name = %s and column_name = %s""",
			(table, column),
		)
	)


def _register_fields():
	# in_create_custom_fields makes Custom Field.on_update skip frappe.db.updatedb (the table sync).
	previous = frappe.flags.in_create_custom_fields
	frappe.flags.in_create_custom_fields = True
	try:
		for doctype, fields in CUSTOM_FIELDS.items():
			for field in fields:
				# A no-op where the Custom Field is already there (a re-run).
				create_custom_field(doctype, {**field, "owner": "Administrator"}, ignore_validate=True)
	finally:
		frappe.flags.in_create_custom_fields = previous
	for doctype in CUSTOM_FIELDS:
		frappe.clear_cache(doctype=doctype)
