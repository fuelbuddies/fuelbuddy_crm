"""Backfill Discount docs for discounts bulk-uploaded onto Opportunities before
the writeback hooks existed.

Two passes, both reusing the live discount_sync handlers (idempotent):
1. Every Opportunity with a discount method -> writeback_opportunity_discount
   (creates/updates its backing Discount, party == opportunity).
2. Every non-cancelled Quotation under such an Opportunity ->
   ensure_quotation_discount (adopt/clone the backing Discount, stamp
   Discount.quotation); submitted Quotations also submit their Discount so the
   1:1 lifecycle matches.

Best-effort per row: a bad legacy record logs and moves on.
"""

import frappe

from fuelbuddy_crm.discount_sync import (
	ensure_quotation_discount,
	submit_quotation_discount,
	writeback_opportunity_discount,
)


def execute():
	opps = frappe.get_all(
		"Opportunity",
		filters={"custom_discount_method": ["not in", ("", None)]},
		pluck="name",
	)
	done = failed = 0
	for i, name in enumerate(opps):
		try:
			writeback_opportunity_discount(frappe.get_doc("Opportunity", name))
			done += 1
		except Exception:
			failed += 1
			frappe.log_error(
				title=f"discount backfill: opportunity {name}"[:140],
				message=frappe.get_traceback(),
			)
		if (i + 1) % 50 == 0:
			frappe.db.commit()
	frappe.db.commit()

	quotations = frappe.get_all(
		"Quotation",
		filters={"custom_opportunity_from": ["in", opps], "docstatus": ["<", 2]},
		fields=["name", "docstatus"],
	)
	q_done = q_failed = 0
	for i, q in enumerate(quotations):
		try:
			doc = frappe.get_doc("Quotation", q.name)
			if q.docstatus == 1:
				submit_quotation_discount(doc)
			else:
				ensure_quotation_discount(doc)
			q_done += 1
		except Exception:
			q_failed += 1
			frappe.log_error(
				title=f"discount backfill: quotation {q.name}"[:140],
				message=frappe.get_traceback(),
			)
		if (i + 1) % 50 == 0:
			frappe.db.commit()
	frappe.db.commit()
	print(
		f"discount backfill: {done}/{len(opps)} opportunities written back ({failed} failed), "
		f"{q_done}/{len(quotations)} quotations ensured ({q_failed} failed)"
	)
