# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""Keep a Quotation 1:1 with its Opportunity.

A Quotation carries two Opportunity links: the standard ``opportunity`` (which
drives every ``fetch_from`` on the Quotation's custom fields) and the custom
``custom_opportunity_from`` (which drives the Discount / Finance Dossier / Sales
Order automation). This module keeps the two in lock-step so they can never
diverge, and enforces at most one non-cancelled Quotation per Opportunity.
"""

import frappe
from frappe import _
from frappe.utils import flt


def guard_totals(doc, method=None):
	"""Quotation ``before_validate`` -> make sure ``grand_total`` / ``base_grand_total``
	are numeric before the controller builds the Payment Schedule. (BUG-001)

	ERPNext's ``calculate_taxes_and_totals()`` returns early for an item-less Quotation
	(``taxes_and_totals.calculate``: ``if not len(self.doc.items): return``), leaving
	``grand_total`` as ``None``. ``set_payment_schedule()`` then multiplies that ``None``
	by the row's invoice portion and raises
	``TypeError: unsupported operand type(s) for *: 'NoneType' and 'float'``.

	Defaulting the totals to 0 here closes that gap. When the Quotation has items,
	``calculate_taxes_and_totals()`` (which runs after ``before_validate``) overwrites
	these with the real figures, so this only takes effect for the empty case."""
	doc.grand_total = flt(doc.get("grand_total"))
	doc.base_grand_total = flt(doc.get("base_grand_total"))


def enforce_one_per_opportunity(doc, method=None):
	"""Quotation ``validate`` -> sync the two Opportunity links and enforce that an
	Opportunity has at most one non-cancelled Quotation."""
	# Whichever link the Quotation was created with wins; mirror it onto the other
	# so fetch_from (uses `opportunity`) and the automation (uses
	# `custom_opportunity_from`) always agree.
	opportunity = doc.get("custom_opportunity_from") or doc.get("opportunity")
	if not opportunity:
		return
	doc.custom_opportunity_from = opportunity
	doc.opportunity = opportunity

	# At most one non-cancelled Quotation per Opportunity.
	duplicate = frappe.db.get_value(
		"Quotation",
		{
			"custom_opportunity_from": opportunity,
			"docstatus": ["<", 2],
			"name": ["!=", doc.name or ""],
		},
		"name",
	)
	if duplicate:
		frappe.throw(
			_(
				"Opportunity {0} already has Quotation {1}. Only one Quotation is allowed per Opportunity."
			).format(opportunity, duplicate)
		)


# Discount-tab fields copied straight from the Opportunity onto the new Quotation
# (identical field names on both doctypes).
_QUOTATION_DISCOUNT_FIELDS = (
	"custom_discount_method",
	"custom_discount_upto_date",
	"custom_percentageper_litre",
	"custom_percentage_value",
	"custom_per_litre_value",
	"custom_max_discount_value",
)

# Slab Discount child-row fields.
_SLAB_FIELDS = ("p_or_v", "qty_limit", "discount_value", "threshold_value", "limit")


def _payment_terms_template_for(payment_term):
	"""Return a ``Payment Terms Template`` that wraps the single ``Payment Term`` chosen
	on the Opportunity, creating it once if needed. (BUG-002)

	The Opportunity/Quotation carry a single custom ``Payment Term`` link
	(``custom_payment_terms``), but ERPNext's standard Payment Schedule is driven by a
	``Payment Terms Template``. Wrapping the term in a one-line, 100%-portion template
	lets the Quotation populate the standard Payment Terms / Payment Schedule section
	from it. Idempotent: the template is named after the term and Payment Terms Template
	autonames by ``template_name``, so a second call reuses the existing one."""
	if not payment_term:
		return None

	template_name = f"FB - {payment_term}"
	if frappe.db.exists("Payment Terms Template", template_name):
		return template_name

	term = frappe.get_doc("Payment Term", payment_term)
	template = frappe.new_doc("Payment Terms Template")
	template.template_name = template_name
	template.append(
		"terms",
		{
			"payment_term": payment_term,
			"description": term.get("description") or payment_term,
			"invoice_portion": 100,
			"due_date_based_on": term.get("due_date_based_on") or "Day(s) after invoice date",
			"credit_days": term.get("credit_days") or 0,
			"credit_months": term.get("credit_months") or 0,
		},
	)
	template.flags.ignore_permissions = True
	template.insert()
	return template_name


@frappe.whitelist()
def create_quotation_from_opportunity(opportunity):
	"""Create a Draft Quotation from an Opportunity, copying the commercial/discount
	details and the Opportunity items, and advance the Opportunity to "Send for
	Quotation". Idempotent: an Opportunity has at most one non-cancelled Quotation
	(also enforced by ``enforce_one_per_opportunity``), so a second call returns the
	existing one.

	Returns ``{"created_quotation": <name>, "already_existed": <bool>}`` so the form
	can warn that the Quotation was created earlier instead of reporting a fresh one.

	(Ported from the "Opportunity Send for Quotation" Server Script -- code-first, no
	DB Server Scripts.)"""
	doc = frappe.get_doc("Opportunity", opportunity)

	if not doc.custom_customer_billing_address:
		frappe.throw(_("Please set the Billing Address on the Opportunity before creating a Quotation."))

	existing = frappe.get_all(
		"Quotation",
		filters={"custom_opportunity_from": doc.name, "docstatus": ["<", 2]},
		pluck="name",
	)
	if existing:
		return {"created_quotation": existing[0], "already_existed": True}

	quotation = frappe.new_doc("Quotation")
	quotation.quotation_to = doc.opportunity_from
	quotation.party_name = doc.party_name
	quotation.company = doc.company
	quotation.currency = doc.currency
	quotation.order_type = "Sales"
	quotation.ignore_pricing_rule = 1
	quotation.custom_opportunity_from = doc.name
	quotation.opportunity = doc.name
	quotation.valid_till = doc.custom_contract_expiry
	quotation.customer_address = doc.custom_customer_billing_address
	quotation.custom_deal_type = doc.custom_deal_type
	quotation.custom_contract_expiry = doc.custom_contract_expiry
	quotation.custom_pricing_model = doc.custom_pricing_model
	quotation.custom_discount_type = frappe.db.get_value("Discount", {"party": doc.name}, "name")

	# Copy the Opportunity Discount tab onto the Quotation Discount tab.
	for field in _QUOTATION_DISCOUNT_FIELDS:
		quotation.set(field, doc.get(field))
	for s in doc.custom_slab_discount or []:
		quotation.append("custom_slab_discount", {f: s.get(f) for f in _SLAB_FIELDS})

	quotation.custom_payment_terms = doc.custom_payment_terms
	# Also drive the Quotation's standard Payment Terms Template / Payment Schedule from
	# the single Payment Term chosen on the Opportunity, so the standard section is
	# populated rather than left empty (BUG-002). The schedule rows themselves are then
	# generated by ERPNext's set_payment_schedule() during insert (guard_totals keeps
	# that safe when the Quotation has no items -- see BUG-001).
	payment_terms_template = _payment_terms_template_for(doc.custom_payment_terms)
	if payment_terms_template:
		quotation.payment_terms_template = payment_terms_template
	quotation.custom_invoicing_frequency = doc.custom_invoicing_frequency
	quotation.custom_invoicing_type = doc.custom_invoicing_type

	rows = [(it.item_code, it.qty or 0, it.uom, it.rate or 0) for it in (doc.items or [])]
	if not rows and doc.custom_product:
		rows.append(
			(doc.custom_product, doc.custom_expected_monthly_volume or 0, doc.custom_uom, doc.custom_rate or 0)
		)

	# A Quotation needs at least one line (items is mandatory). Fail with a clear,
	# actionable message instead of letting ERPNext raise either a TypeError from
	# set_payment_schedule() on a None grand_total (BUG-001) or a raw MandatoryError.
	if not rows:
		frappe.throw(
			_("Add at least one Product / Item on the Opportunity before creating a Quotation.")
		)

	# Insert items at their original price -- do NOT pre-discount the rate or the price
	# list rate. The discount is captured on the Quotation's Discount tab, not by
	# reducing the item price here.
	for item_code, qty, uom, base_rate in rows:
		quotation.append(
			"items",
			{
				"item_code": item_code,
				"qty": qty,
				"uom": uom,
				"rate": base_rate,
				"price_list_rate": base_rate,
				"prevdoc_doctype": "Opportunity",
				"prevdoc_docname": doc.name,
			},
		)

	quotation.taxes_and_charges = "UAE VAT 5%"
	template = frappe.get_doc("Sales Taxes and Charges Template", "UAE VAT 5%")
	for t in template.taxes:
		quotation.append(
			"taxes",
			{
				"charge_type": t.charge_type,
				"account_head": t.account_head,
				"description": t.description,
				"rate": t.rate,
				"cost_center": t.cost_center,
				"included_in_print_rate": t.included_in_print_rate,
			},
		)

	quotation.insert(ignore_permissions=True)  # stays Draft (no submit)

	# Advance the sales stage only when a Quotation is freshly created, so re-clicking
	# the button on an Opportunity that already has one keeps its stage.
	frappe.db.set_value("Opportunity", doc.name, "sales_stage", "Send for Quotation")
	return {"created_quotation": quotation.name, "already_existed": False}
