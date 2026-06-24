# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""Keep a Quotation's Discount in lock-step with the Quotation.

Each Quotation owns exactly one Discount, linked 1:1 by ``Discount.quotation``.
The Discount is copied once from the Opportunity's backing/template Discount
when the Quotation is created; from then on its docstatus follows the
Quotation -- submitting the Quotation submits the Discount, cancelling the
Quotation cancels it.

The submit/cancel propagation is intentionally *atomic*: if the Discount cannot
be submitted/cancelled the exception is allowed to propagate so the whole
Quotation submit/cancel rolls back, rather than leaving a half-applied state.
"""

import frappe

# Parent Discount fields copied from the Opportunity template onto the
# per-Quotation Discount. `quotation`/`party` are set explicitly below.
_DISCOUNT_COPY_FIELDS = (
	"customer",
	"product",
	"company",
	"discount_type",
	"p_or_v",
	"percentage_value",
	"per_litre_value",
	"threshold_value",
	"approved",
	"date",
	"threshold_days",
	"payment_terms",
)

# Slab Discount child-row fields.
_SLAB_COPY_FIELDS = ("p_or_v", "qty_limit", "discount_value", "threshold_value", "limit")


def get_quotation_discount(quotation):
	"""Name of the Discount that belongs 1:1 to this Quotation, or None."""
	return frappe.db.get_value("Discount", {"quotation": quotation}, "name")


def _template_discount_for(doc):
	"""The Discount to copy from the first time: the one the Quotation was
	created against (``custom_discount_type``) or, failing that, the
	Opportunity's backing Discount (``party == opportunity``)."""
	template = doc.get("custom_discount_type")
	if template and frappe.db.exists("Discount", template):
		return template
	if doc.get("custom_opportunity_from"):
		return frappe.db.get_value("Discount", {"party": doc.custom_opportunity_from}, "name")
	return None


def ensure_quotation_discount(doc, method=None):
	"""Guarantee a Draft Discount linked 1:1 to this Quotation.

	Copies the Opportunity/template Discount the first time and stamps
	``Discount.quotation``; idempotent thereafter. Also repoints the Quotation's
	``custom_discount_type`` link at its own Discount so the form shows the
	document whose lifecycle it controls. Quotations with no source Discount
	(e.g. created outside the Opportunity flow) are left untouched."""
	if get_quotation_discount(doc.name):
		return

	template = _template_discount_for(doc)
	if not template:
		return

	src = frappe.get_doc("Discount", template)
	dc = frappe.new_doc("Discount")
	for field in _DISCOUNT_COPY_FIELDS:
		dc.set(field, src.get(field))
	dc.quotation = doc.name
	dc.party = doc.get("custom_opportunity_from") or src.get("party")
	for row in src.slab_discount or []:
		dc.append("slab_discount", {f: row.get(f) for f in _SLAB_COPY_FIELDS})
	dc.flags.ignore_permissions = True
	dc.insert()

	if doc.get("custom_discount_type") != dc.name:
		# db.set_value (not doc.save) -- this runs inside the Quotation's own
		# after_insert; saving the doc again would re-fire its events.
		frappe.db.set_value("Quotation", doc.name, "custom_discount_type", dc.name)


def submit_quotation_discount(doc, method=None):
	"""On Quotation submit -> submit its Discount. Atomic: a failure here is
	allowed to propagate so the Quotation submit rolls back too (per design)."""
	ensure_quotation_discount(doc)
	name = get_quotation_discount(doc.name)
	if not name:
		return
	dc = frappe.get_doc("Discount", name)
	if dc.docstatus == 0:
		dc.flags.ignore_permissions = True
		dc.submit()


def cancel_quotation_discount(doc, method=None):
	"""On Quotation cancel -> cancel its Discount. Atomic: a failure here is
	allowed to propagate so the Quotation cancel rolls back too (per design)."""
	name = get_quotation_discount(doc.name)
	if not name:
		return
	dc = frappe.get_doc("Discount", name)
	if dc.docstatus == 1:
		dc.flags.ignore_permissions = True
		dc.cancel()
