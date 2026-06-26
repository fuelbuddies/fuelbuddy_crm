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
from frappe import _

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

# Opportunity discount-tab fields. The slab table (`custom_slab_discount`) is
# compared/propagated separately. The Quotation carries the same field names, so
# these copy across 1:1; the Discount doc and Finance Dossier use the maps below.
_OPP_DISCOUNT_FIELDS = (
	"custom_discount_method",
	"custom_percentageper_litre",
	"custom_percentage_value",
	"custom_per_litre_value",
	"custom_max_discount_value",
	"custom_discount_upto_date",
)

# Discount-doc field <- Opportunity discount-tab field (mirrors the Opportunity
# Discount Writeback server script, which maintains the Opportunity's backing Discount).
_OPP_TO_DISCOUNT = {
	"discount_type": "custom_discount_method",
	"p_or_v": "custom_percentageper_litre",
	"percentage_value": "custom_percentage_value",
	"per_litre_value": "custom_per_litre_value",
	"threshold_value": "custom_max_discount_value",
	"date": "custom_discount_upto_date",
}

# Finance Dossier field <- Opportunity discount-tab field (the FD uses un-prefixed
# field names; it has no discount "upto date").
_OPP_TO_FD = {
	"discount_method": "custom_discount_method",
	"percentageper_litre": "custom_percentageper_litre",
	"percentage_value": "custom_percentage_value",
	"per_litre_value": "custom_per_litre_value",
	"max_discount_value": "custom_max_discount_value",
}


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


# --- Opportunity discount -> downstream (Quotation / Discount / Finance Dossier) ---
#
# The Opportunity discount tab is the source of truth. A Quotation copies it once at
# creation; from then on edits on the Opportunity must flow down to the (still-Draft)
# Quotation, its 1:1 Discount and its Finance Dossier. Once any of those is submitted
# the discount is part of a signed contract, so the edit is blocked on the Opportunity
# instead of silently drifting out of sync.


def _linked_quotation(opportunity):
	"""The single non-cancelled Quotation for this Opportunity (``{name, docstatus}``)
	or None. ``enforce_one_per_opportunity`` guarantees at most one."""
	return frappe.db.get_value(
		"Quotation",
		{"custom_opportunity_from": opportunity, "docstatus": ["<", 2]},
		["name", "docstatus"],
		as_dict=True,
	)


def _slab_signature(rows):
	return [tuple(r.get(f) for f in _SLAB_COPY_FIELDS) for r in (rows or [])]


def _opportunity_discount_changed(doc):
	"""Whether any Opportunity discount-tab field (or the slab table) differs from the
	last saved version. False for a brand-new Opportunity (nothing exists downstream)."""
	before = doc.get_doc_before_save()
	if before is None:
		return False
	for field in _OPP_DISCOUNT_FIELDS:
		if (before.get(field) or None) != (doc.get(field) or None):
			return True
	return _slab_signature(before.get("custom_slab_discount")) != _slab_signature(
		doc.get("custom_slab_discount")
	)


def guard_opportunity_discount(doc, method=None):
	"""Opportunity ``validate`` -> block a discount change once the deal is contracted.
	The discount is locked the moment the Quotation or its Finance Dossier is submitted;
	propagation only touches Drafts, so allowing the change afterwards would silently
	drift from the signed contract."""
	if not _opportunity_discount_changed(doc):
		return
	quotation = _linked_quotation(doc.name)
	if not quotation:
		return
	if quotation.docstatus == 1:
		frappe.throw(
			_(
				"Quotation {0} is already submitted, so its discount is locked. "
				"Cancel/amend the Quotation to change the discount."
			).format(quotation.name)
		)
	dossier = frappe.db.get_value(
		"Finance Dossier",
		{"finance_dossier_from": "Quotation", "id": quotation.name, "docstatus": 1},
		"name",
	)
	if dossier:
		frappe.throw(
			_(
				"Finance Dossier {0} is already submitted, so the discount is locked. "
				"Cancel/amend it to change the discount."
			).format(dossier)
		)


def propagate_opportunity_discount(doc, method=None):
	"""Opportunity ``on_update`` -> push a changed discount down to the still-Draft
	Quotation, its 1:1 Discount and its Finance Dossier. Submitted targets are never
	reached (``guard_opportunity_discount`` blocks the change first). Best-effort: a
	failure is logged rather than rolling back the Opportunity save."""
	if not _opportunity_discount_changed(doc):
		return
	try:
		quotation = _linked_quotation(doc.name)
		if not quotation or quotation.docstatus != 0:
			return
		_propagate_to_quotation(doc, quotation.name)
		_propagate_to_discount(doc, quotation.name)
		_propagate_to_dossier(doc, quotation.name)
	except Exception:
		frappe.log_error(
			title=f"Opportunity discount sync failed: {doc.name}"[:140],
			message=frappe.get_traceback(),
		)


def _copy_slab(src_rows, target, fieldname):
	target.set(fieldname, [])
	for row in src_rows or []:
		target.append(fieldname, {f: row.get(f) for f in _SLAB_COPY_FIELDS})


def _propagate_to_quotation(opp, quotation):
	q = frappe.get_doc("Quotation", quotation)
	for field in _OPP_DISCOUNT_FIELDS:
		q.set(field, opp.get(field))
	_copy_slab(opp.get("custom_slab_discount"), q, "custom_slab_discount")
	q.flags.ignore_permissions = True
	q.save()


def _propagate_to_discount(opp, quotation):
	name = get_quotation_discount(quotation)
	if not name:
		return
	dc = frappe.get_doc("Discount", name)
	if dc.docstatus != 0:
		return
	for target, source in _OPP_TO_DISCOUNT.items():
		dc.set(target, opp.get(source))
	_copy_slab(opp.get("custom_slab_discount"), dc, "slab_discount")
	dc.flags.ignore_permissions = True
	dc.save()


def _propagate_to_dossier(opp, quotation):
	from fuelbuddy_crm.finance_dossier import get_quotation_dossier

	name = get_quotation_dossier(quotation)
	if not name:
		return
	fd = frappe.get_doc("Finance Dossier", name)
	if fd.docstatus != 0:
		return
	for target, source in _OPP_TO_FD.items():
		fd.set(target, opp.get(source))
	_copy_slab(opp.get("custom_slab_discount"), fd, "slab_discount")
	fd.flags.ignore_permissions = True
	fd.save()
