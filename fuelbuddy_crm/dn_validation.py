# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""Delivery Note application-level dedup.

`custom_invoiced_item_id` links a DN to its Hasura invoiced_item. It is deliberately
NOT a unique DB index on prod: a versioned amendment (cancel the original, create a
"+1" version) reuses the SAME id across the cancelled original and the live version,
which a single-column unique index would reject.

So enforce the true invariant in application code instead: at most ONE non-cancelled
Delivery Note (docstatus < 2) may exist per custom_invoiced_item_id. Cancelled DNs
(docstatus 2) don't count, so versioning is allowed; a genuine duplicate — two live
DNs for one invoiced_item — is blocked.

Note: like any validate-time check-then-act, this catches sequential/re-delivered
duplicates, not a truly simultaneous double-insert (no row lock). The out-of-band
punch path is effectively serialized, so that residual race is negligible; add a
row lock only if concurrent duplicate creates are ever observed.
"""

import frappe
from frappe import _


def enforce_single_active_dn(doc, method=None):
	iid = doc.get("custom_invoiced_item_id")
	if not iid:
		return  # hand-built / non-punch DNs without the link are not deduped here

	if doc.get("is_return"):
		# A Sales Return against the DN copies custom_invoiced_item_id (the field is not
		# no_copy) but is a negative-qty companion doc, not a second punch — never a duplicate.
		return

	existing = frappe.db.get_value(
		"Delivery Note",
		{
			"custom_invoiced_item_id": iid,
			"name": ["!=", doc.name or ""],
			"docstatus": ["<", 2],  # exclude cancelled -> versioned amendments are allowed
			"is_return": ["!=", 1],  # a live return must not block a legitimate re-punch/amend
		},
		"name",
	)
	if existing:
		frappe.throw(
			_("A non-cancelled Delivery Note ({0}) already exists for invoiced_item {1}.").format(
				existing, iid
			),
			title=_("Duplicate Delivery Note"),
		)
