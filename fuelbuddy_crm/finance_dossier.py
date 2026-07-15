# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""Finance Dossier is created from the Quotation (not the Opportunity).

When a Quotation is created we auto-create a single Draft Finance Dossier linked
1:1 to it (``finance_dossier_from == "Quotation"``, ``id == quotation``), copying
the commercial/discount details over. This replaces the old "Send for Finance
Dossier" button on the Opportunity.

Creation is best-effort: a failure here must never roll back the Quotation's
own insert, so any exception is logged to the Error Log instead of propagating.
"""

import frappe

# Error Log prefix so all Finance-Dossier-from-Quotation issues filter together.
_LOG_PREFIX = "Finance Dossier"


def _log(title, quotation=None, traceback=False):
	try:
		parts = []
		if quotation:
			parts.append(f"Quotation: {quotation}")
		if traceback:
			parts.append(frappe.get_traceback())
		frappe.log_error(title=f"{_LOG_PREFIX}: {title}"[:140], message="\n".join(parts) or title)
	except Exception:
		pass


def get_quotation_dossier(quotation):
	"""Name of the (non-cancelled) Finance Dossier that belongs to this Quotation."""
	return frappe.db.get_value(
		"Finance Dossier",
		{"finance_dossier_from": "Quotation", "id": quotation, "docstatus": ["<", 2]},
		"name",
	)


def sync_source_reference(doc, method=None):
	"""Finance Dossier after_insert / on_submit / on_cancel -> stamp the CURRENT live
	dossier's name on the source Quotation (custom_finance_dossier, read-only).

	Always recomputed via get_quotation_dossier, so a cancel CLEARS the link (a
	Quotation pointing at a cancelled doc would fail Frappe's link validation on
	every save) and an amendment re-stamps it. Server-side replacement for the old
	finance_dossier.js after_save writeback, which only fired on browser saves (and
	targeted a field that never existed)."""
	if doc.finance_dossier_from != "Quotation" or not doc.id:
		return
	try:
		frappe.db.set_value(
			"Quotation", doc.id, "custom_finance_dossier",
			get_quotation_dossier(doc.id), update_modified=False,
		)
	except Exception:
		_log("failed to stamp custom_finance_dossier", quotation=doc.id, traceback=True)


def require_submitted_dossier(doc, method=None):
	"""Quotation before_submit -> its Finance Dossier must already be SUBMITTED.

	The Finance Dossier is approved first, then the Quotation is submitted (which
	is what kicks off the contract Sales Order). Blocking here keeps a Quotation
	from entering the SO pipeline without an approved dossier."""
	dossier = get_quotation_dossier(doc.name)
	if not dossier:
		cancelled = frappe.db.get_value(
			"Finance Dossier",
			{"finance_dossier_from": "Quotation", "id": doc.name, "docstatus": 2},
			"name",
			order_by="creation desc",
		)
		if cancelled:
			frappe.throw(
				frappe._("Finance Dossier {0} is cancelled. Amend it and submit the amendment before submitting this Quotation.").format(cancelled)
			)
		frappe.throw(
			frappe._("No Finance Dossier is linked to this Quotation. Create and submit it before submitting the Quotation.")
		)
	if frappe.db.get_value("Finance Dossier", dossier, "docstatus") != 1:
		frappe.throw(
			frappe._("Finance Dossier {0} must be submitted before submitting this Quotation.").format(dossier)
		)


def create_for_quotation(doc, method=None):
	"""Quotation after_insert -> create its Draft Finance Dossier (idempotent).

	Best-effort: never raises, so a Finance Dossier problem can't roll back the
	Quotation insert. A missing Address (required on Finance Dossier) is the one
	hard prerequisite -- without it we skip and log."""
	try:
		if get_quotation_dossier(doc.name):
			return

		# The Finance Dossier uses the SAME billing address as the Quotation
		# (Quotation.customer_address is the billing address). Billing is enforced
		# upstream when the Quotation is created, so there is no shipping/Opportunity
		# fallback here; if somehow absent, skip (Address is mandatory on the FD).
		address = doc.get("customer_address")
		if not address:
			_log("skipped: Quotation has no billing address", quotation=doc.name)
			return

		# custom_discount_type may have been repointed at the Quotation's own
		# Discount by discount_sync.ensure_quotation_discount (runs first); read
		# the persisted value rather than the stale in-memory one.
		discount = frappe.db.get_value("Quotation", doc.name, "custom_discount_type")

		fd = frappe.new_doc("Finance Dossier")
		fd.finance_dossier_from = "Quotation"
		fd.id = doc.name
		fd.address = address
		# Quotation total_qty is the contracted monthly volume; fall back to the
		# Opportunity's Expected Monthly Volume when the Quotation has no items yet.
		volume = doc.get("total_qty")
		if not volume and doc.get("custom_opportunity_from"):
			volume = frappe.db.get_value(
				"Opportunity", doc.custom_opportunity_from, "custom_expected_monthly_volume"
			)
		fd.expected_monthly_volume = volume
		fd.deal_type = doc.get("custom_deal_type")
		fd.pricing_model = doc.get("custom_pricing_model")
		fd.payment_term = doc.get("custom_payment_terms")
		# "Payment Terms" on the Commercials tab (the `credit_days` field) also carries
		# the agreed Payment Term down from the Opportunity (via the Quotation).
		fd.credit_days = doc.get("custom_payment_terms")
		fd.contract_expiry = doc.get("custom_contract_expiry")
		fd.invoicing_frequency = doc.get("custom_invoicing_frequency")
		fd.invoicing_type = doc.get("custom_invoicing_type")
		fd.discount = discount
		fd.discount_method = doc.get("custom_discount_method")
		fd.percentageper_litre = doc.get("custom_percentageper_litre")
		fd.percentage_value = doc.get("custom_percentage_value")
		fd.per_litre_value = doc.get("custom_per_litre_value")
		fd.max_discount_value = doc.get("custom_max_discount_value")
		for s in (doc.get("custom_slab_discount") or []):
			fd.append(
				"slab_discount",
				{
					"p_or_v": s.p_or_v,
					"qty_limit": s.qty_limit,
					"discount_value": s.discount_value,
					"threshold_value": s.threshold_value,
					"limit": s.limit,
				},
			)
		fd.flags.ignore_permissions = True
		fd.insert()  # stays Draft (no submit)
	except Exception:
		_log("creation failed", quotation=getattr(doc, "name", None), traceback=True)
