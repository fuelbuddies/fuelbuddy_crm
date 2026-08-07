# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""Cross-cutting CRM field validations wired in via ``doc_events`` (code-first, no DB
Server Scripts):

  - Discount-tab values must not be negative (Opportunity / Quotation) -- BUG-004.
  - An Opportunity's Contract Expiry / Valid Till must not precede its transaction
    date -- BUG-007.
  - Server-side mirrors of the form Client Scripts' calculations/rules, so bulk
    upload (Data Import) -- where Client Scripts never run -- produces the same
    values: Opportunity Value amount, UOM default + whitelist, discount Upto Date
    default, and the HSE reason-for-rejection rule.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

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


def apply_opportunity_calculations(doc, method=None):
	"""Server-side mirror of the "Price List Rate In Oppportunity" and "Add Discount On
	Opportunity" Client Scripts, so bulk upload (Data Import) computes/validates the same
	way the form does.

	  - custom_uom defaults to Litre when a product is set.
	  - custom_uom must be one of the product's UOMs (the form enforces this via a
	    set_query filter, which an import bypasses).
	  - custom_rate, when empty, is fetched from the ex-VAT price list and converted to
	    custom_uom -- same source and conversion the form uses. A rate supplied in the
	    import (or overridden on the form) is kept as-is.
	  - opportunity_amount = custom_expected_monthly_volume * custom_rate, and
	    base_opportunity_amount = opportunity_amount * conversion_rate.
	    Skipped when neither volume nor rate is set (legacy docs without the
	    Opportunity Value section keep their manually-entered amount).
	  - custom_discount_upto_date defaults to custom_contract_expiry."""
	if doc.get("custom_product"):
		if not doc.get("custom_uom"):
			doc.custom_uom = "Litre"
		allowed_uoms = frappe.get_all(
			"UOM Conversion Detail",
			filters={"parenttype": "Item", "parent": doc.custom_product},
			pluck="uom",
		)
		if doc.custom_uom not in allowed_uoms:
			frappe.throw(
				_("UOM {0} is not defined on Item {1}. Allowed: {2}").format(
					doc.custom_uom, doc.custom_product, ", ".join(allowed_uoms)
				)
			)
		if not flt(doc.get("custom_rate")):
			doc.custom_rate = _ex_vat_rate(doc.custom_product, doc.custom_uom)

	volume = flt(doc.get("custom_expected_monthly_volume"))
	rate = flt(doc.get("custom_rate"))
	if volume or rate:
		doc.opportunity_amount = volume * rate
		doc.base_opportunity_amount = doc.opportunity_amount * (flt(doc.get("conversion_rate")) or 1)

	default_discount_upto_date(doc)


# The price list the Opportunity Value rate comes from; maintained in the item's stock UOM.
_EX_VAT_PRICE_LIST = "Selling Price List Excluding VAT"


def _ex_vat_rate(item_code, uom, transaction_date=None):
	"""Ex-VAT price-list rate for the item valid on ``transaction_date`` (default
	today), converted to ``uom``.

	Item Price rows on this site are month-scoped (valid_from/valid_upto), so
	resolution goes through erpnext's get_item_price: validity window filtered,
	newest valid_from wins (IDEV-3066 — "creation desc" let future/backfilled rows
	shadow the rate actually in force). Price list is maintained in the item's STOCK
	uom; the result is multiplied by the same conversion factor Sales Order Item
	uses (get_conversion_factor). Returns 0 (with a warning, like the client's
	alert) when no valid ex-VAT price exists."""
	from erpnext.stock.get_item_details import get_conversion_factor, get_item_price

	rows = get_item_price(
		frappe._dict(
			price_list=_EX_VAT_PRICE_LIST,
			uom=frappe.db.get_value("Item", item_code, "stock_uom"),
			transaction_date=transaction_date or nowdate(),
		),
		item_code,
	)
	base_rate = rows[0][1] if rows else 0
	if not base_rate:
		frappe.msgprint(
			_("No '{0}' price found for {1}; rate set to 0.").format(_EX_VAT_PRICE_LIST, item_code),
			indicator="orange",
		)
		return 0
	cf = flt(get_conversion_factor(item_code, uom).get("conversion_factor")) or 1
	return flt(base_rate) * cf


@frappe.whitelist()
def get_ex_vat_rate(item_code, uom, transaction_date=None):
	"""Client-callable ex-VAT rate lookup, so the "Price List Rate In ..." Client
	Scripts share the server's validity-aware resolution (IDEV-3066)."""
	return _ex_vat_rate(item_code, uom, transaction_date)


def default_discount_upto_date(doc, method=None):
	"""Discount "Upto Date" defaults to the Contract Expiry (mirrors the "Add Discount On
	Opportunity" / "Quotation Discount Tab" Client Scripts for Data Import)."""
	if not doc.get("custom_discount_upto_date") and doc.get("custom_contract_expiry"):
		doc.custom_discount_upto_date = doc.custom_contract_expiry


def validate_non_negative_opportunity_values(doc, method=None):
	"""Expected Monthly Volume and Rate must not be negative (they drive
	opportunity_amount = volume * rate, so a negative slips a negative deal value
	into the pipeline). Authoritative server-side check; opportunity.js mirrors it
	client-side for immediate feedback."""
	for fieldname, label in (
		("custom_expected_monthly_volume", "Expected Monthly Volume"),
		("custom_rate", "Rate"),
	):
		if flt(doc.get(fieldname)) < 0:
			frappe.throw(_("{0} cannot be negative.").format(_(label)))


def validate_hse_checks(doc, method=None):
	"""Every Opportunity HSE row needs either a linked HSE Check or a Reason for
	Rejection -- exactly one of the two.

	Intended by the "HSE_Check_Rejection_Validation" Client Script, which is a dead
	no-op: it tests ``row.custom_hse_check === 0/1`` but the real field is ``hse_check``
	(a Link to HSE Inspection, never the custom_-prefixed name), so ``undefined``
	matches neither branch. This is the authoritative check, using the real field."""
	for row in doc.get("custom_opportunity_hse") or []:
		row_label = _("Row {0} - {1}").format(row.idx, row.get("address") or "")
		if not row.get("hse_check") and not row.get("reason_for_rejection"):
			frappe.throw(
				_("{0}: Reason for rejection is required when there is no HSE Check.").format(row_label)
			)
		if row.get("hse_check") and row.get("reason_for_rejection"):
			frappe.throw(
				_("{0}: Reason for rejection must be empty if there is an HSE Check.").format(row_label)
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


def sync_opportunity_value_item(doc, method=None):
	"""Opportunity before_save -> replicate the Opportunity Value section
	(custom_product / volume / rate) into the standard items table and recompute the
	items totals. Moved here from the "Item Creation at Opportunity Level" Server
	Script (see patches.remove_crm_server_scripts)."""
	if doc.get("custom_product"):
		qty = flt(doc.get("custom_expected_monthly_volume"))
		rate = flt(doc.get("custom_rate"))

		existing_row = None
		for item in (doc.items or []):
			if item.item_code == doc.custom_product:
				existing_row = item
				break

		if existing_row:
			existing_row.uom = doc.get("custom_uom")
			existing_row.qty = qty
			existing_row.rate = rate
			existing_row.base_rate = rate
			existing_row.amount = rate * qty
			existing_row.base_amount = rate * qty
		else:
			doc.append("items", {
				"item_code": doc.custom_product,
				"uom": doc.get("custom_uom"),
				"qty": qty,
				"rate": rate,
				"base_rate": rate,
				"amount": rate * qty,
				"base_amount": rate * qty,
			})

		doc.run_method("set_missing_values")

	doc.total = sum(flt(it.amount) for it in (doc.items or []))
	doc.base_total = sum(flt(it.base_amount) or flt(it.amount) for it in (doc.items or []))
