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
		fd.expected_monthly_volume = doc.get("total_qty")
		fd.deal_type = doc.get("custom_deal_type")
		fd.pricing_model = doc.get("custom_pricing_model")
		fd.payment_term = doc.get("custom_payment_terms")
		fd.contract_expiry = doc.get("custom_contract_expiry")
		fd.invoicing_frequency = doc.get("custom_invoicing_frequency")
		fd.invoice_frequency = doc.get("custom_invoicing_frequency")
		fd.invoicing_type = doc.get("custom_invoicing_type")
		fd.discount = discount
		fd.discount_type = discount
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
