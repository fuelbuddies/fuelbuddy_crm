# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""Force Majeure Trigger / Pricing grant access to two app-owned roles (IDEV-3129):
Force Majeure Manager (approve, submit, cancel) and Force Majeure User (draft and
send for approval). Shipping the roles with the app means a site gets them on
install instead of someone recreating them by hand. DocType permissions are
link-validated against `tabRole` during the model sync, so they must exist BEFORE
the sync -- hence pre_model_sync. No-op once present."""

import frappe

ROLES = ("Force Majeure Manager", "Force Majeure User")


def execute():
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)
