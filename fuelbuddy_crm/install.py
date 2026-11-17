# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""Install-time setup: the custom fields this app owns in code (custom_fields.CUSTOM_FIELDS).

``after_install`` and ``after_migrate`` both apply them with ``create_custom_fields(update=True)``,
which matches an existing field by (DocType, fieldname) and saves it only when a declared value
differs. On a site that already has a field exactly as declared, nothing is written; on a site
without it, it is created; on a site where someone has edited it by hand, it is put back.
"""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from fuelbuddy_crm.custom_fields import CUSTOM_FIELDS


def after_install():
	apply_custom_fields()


def after_migrate():
	apply_custom_fields()


def apply_custom_fields():
	create_custom_fields(CUSTOM_FIELDS, update=True)
