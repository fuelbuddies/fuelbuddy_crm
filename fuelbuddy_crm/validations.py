# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""Cross-cutting CRM field validations wired in via ``doc_events`` (code-first, no DB
Server Scripts):

  - Discount-tab values must not be negative (Opportunity / Quotation) -- BUG-004.
  - An Opportunity's Contract Expiry / Valid Till must not precede its transaction
    date -- BUG-007.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

# Discount-tab header value fields (identical names on Opportunity and Quotation) and a
# human label for each, used in the validation message.
_DISCOUNT_VALUE_FIELDS = {
	"custom_percentage_value": "Percentage Value",
	"custom_per_litre_value": "Per Litre Value",
	"custom_max_discount_value": "Max Discount Value",
}

# Slab Discount child-row value fields and their labels.
_SLAB_VALUE_FIELDS = {
	"qty_limit": "Quantity Limit",
	"discount_value": "Discount Value",
	"threshold_value": "Threshold Value",
}


def validate_discount_values(doc, method=None):
	"""Reject negative discount inputs on the Discount tab (BUG-004).

	A negative discount is silently coerced to 0 today (saved with no feedback). Fail
	loudly instead, on both the header fields and the Slab Discount rows, so the user
	corrects the entry rather than unknowingly losing it."""
	for field, label in _DISCOUNT_VALUE_FIELDS.items():
		if flt(doc.get(field)) < 0:
			frappe.throw(_("{0} cannot be negative.").format(_(label)))

	for row in doc.get("custom_slab_discount") or []:
		for field, label in _SLAB_VALUE_FIELDS.items():
			if flt(row.get(field)) < 0:
				frappe.throw(
					_("Slab Discount row {0}: {1} cannot be negative.").format(row.idx, _(label))
				)


def validate_discount(doc, method=None):
	"""Validate a Discount by its type.

	Replaces the DB "Discount User Validation" Server Script, which required a slab
	*unconditionally* -- so a **Non-Slab Discount** was wrongly forced to carry at least
	one slab ("At least one discount slab must be configured."). The slab rules only make
	sense for a Slab Discount:

	  - Slab Discount:     at least one slab; every row but the last has limit "Upper" and
	                       the last has "Lower"; a single p_or_v across all rows.
	  - Non-Slab Discount: no slab requirement (the per-litre / percentage value applies).
	"""
	if doc.get("discount_type") != "Slab Discount":
		return

	slabs = doc.get("slab_discount") or []
	if not slabs:
		frappe.throw(_("At least one discount slab must be configured."))

	last = len(slabs) - 1
	for i, slab in enumerate(slabs):
		if i < last and slab.get("limit") != "Upper":
			frappe.throw(
				_("Incorrect slab configuration: Slab {0} should have limit 'Upper'.").format(i + 1)
			)
		if i == last and slab.get("limit") != "Lower":
			frappe.throw(
				_(
					"Incorrect slab configuration: Last slab (Slab {0}) should have limit 'Lower'."
				).format(i + 1)
			)

	if len({slab.get("p_or_v") for slab in slabs}) > 1:
		frappe.throw(
			_("All slabs must have the same value. Either 'Per Litre' or 'Percentage', but not both.")
		)


def block_manual_sales_order(doc, method=None):
	"""Restrict Sales Order creation to the approved CRM chain (BUG-012).

	Interactive creation must originate from a Quotation whose Finance Dossier is
	submitted/approved (Opportunity → Quotation → Finance Dossier → Sales Order). Two
	things are blocked: creating an SO by hand from *Selling > Sales Order* (no source
	Quotation), and creating one from a Quotation via the standard "Create Sales Order"
	button before that Quotation's Finance Dossier is approved.

	Programmatic creation is trusted and passes: the contract automation
	(``fuelbuddy_crm.sales_automation``) and integrations insert with
	``ignore_permissions`` — and the automation already only runs once the Finance Dossier
	is ready. The source Quotation is read from ``custom_quotation`` (set by the
	automation) or from an item's ``prevdoc_docname`` (set by the standard mapper).

	Runs on ``before_insert`` so it only gates fresh creation, never edits to existing
	Sales Orders."""
	if getattr(doc.flags, "ignore_permissions", False):
		return  # contract automation / integrations (already FD-gated upstream)

	# Escape hatch: when "Enable Manual Sales Order Creation" is on in Fuelbuddy
	# Settings, direct/manual SO creation is explicitly permitted -- skip the
	# require-approved-Quotation chain entirely. Automatic creation (Quotation submit
	# + monthly scheduler) is unaffected either way. Default off restores BUG-012.
	if frappe.db.get_single_value("Fuelbuddy Settings", "enable_manual_order_creation"):
		return

	quotation = doc.get("custom_quotation")
	if not quotation:
		for row in doc.get("items") or []:
			if row.get("prevdoc_doctype") == "Quotation" and row.get("prevdoc_docname"):
				quotation = row.get("prevdoc_docname")
				break

	if not quotation:
		frappe.throw(
			_(
				"A Sales Order must be created from an approved Quotation (via the "
				"Opportunity → Quotation → Finance Dossier flow). Manual creation is not allowed."
			)
		)

	approved_dossier = frappe.db.get_value(
		"Finance Dossier",
		{"finance_dossier_from": "Quotation", "id": quotation, "docstatus": 1},
		"name",
	)
	if not approved_dossier:
		frappe.throw(
			_(
				"Cannot create a Sales Order for Quotation {0}: its Finance Dossier must be "
				"submitted / approved first."
			).format(quotation)
		)


def validate_opportunity_valid_till(doc, method=None):
	"""Block an Opportunity whose Contract Expiry / Valid Till is before its transaction
	date (BUG-007).

	Mirrors ERPNext's ``Quotation.validate_valid_till`` so the Opportunity can't carry
	an already-expired validity into the deal. ``transaction_date`` defaults to today on
	a new Opportunity, so this also rejects a past expiry on creation."""
	valid_till = doc.get("custom_contract_expiry")
	transaction_date = doc.get("transaction_date")
	if valid_till and transaction_date and getdate(valid_till) < getdate(transaction_date):
		frappe.throw(_("Valid till date cannot be before transaction date"))
