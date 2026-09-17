# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""Force Majeure pricing override (IDEV-3129).

During a declared Force Majeure event the contract rate is replaced, for named
customers only, by a flat interim rate agreed for the duration. The override is
decided PER DELIVERY and lands on the Sales Invoice; Sales Orders and Delivery
Notes are never touched, so the contract stays intact and there is nothing to
undo when the event ends.

Two gates decide whether Force Majeure can apply to a customer at all -- fail
either and the caller runs its normal flow untouched:

  global    ``Fuelbuddy Settings.enable_force_majeure`` is on, and at least one
            ``Force Majeure Trigger`` is submitted;
  customer  the customer has at least one APPROVED (docstatus 1)
            ``Force Majeure Pricing``. There is no per-customer flag: an approved
            Pricing IS the opt-in, cancelling it is the opt-out.

Past both, each delivery is decided on ITS OWN posting date: a submitted Trigger
AND an approved Pricing must both cover that date, and the Pricing must carry a
non-zero rate for the item. Deliveries that pass are billed at that flat rate
with the deal discount suppressed; deliveries that don't keep normal pricing. An
invoice covering a window that straddles the event therefore carries two lines
for the same item -- the outside-period quantity first at contract pricing, then
the inside-period quantity at the Force Majeure rate -- which is the intended
outcome, not a side effect.

Every forced line is stamped with the Pricing that supplied its rate. Once the
invoice is submitted, Frappe's own back-link check refuses to cancel (and so to
amend) that Pricing until the invoice is cancelled, so a billed rate can never be
pulled out from under the invoice.
"""

import frappe
from frappe.utils import flt, getdate


def fm_resolver(customer):
	"""The two gates, then a per-date decision.

	Returns None when Force Majeure cannot apply to ``customer`` at all -- run the
	normal flow. Otherwise returns ``resolve(date) -> Force Majeure Pricing | None``,
	which is the per-delivery decision. Cheapest checks first: the settings flag is
	one cached Single read and is off for everyone outside an event.
	"""
	if not frappe.get_cached_doc("Fuelbuddy Settings").get("enable_force_majeure"):
		return None
	triggers = frappe.get_all(
		"Force Majeure Trigger",
		filters={"docstatus": 1},
		fields=["global_start_date", "global_end_date"],
	)
	if not triggers:
		return None
	pricings = frappe.get_all(
		"Force Majeure Pricing",
		filters={"customer": customer, "docstatus": 1},
		fields=["name", "effective_start", "effective_end"],
	)
	if not pricings:
		return None

	def resolve(on):
		on = getdate(on)
		if not any(
			getdate(t.global_start_date) <= on
			and (not t.global_end_date or on <= getdate(t.global_end_date))
			for t in triggers
		):
			return None
		for p in pricings:
			if getdate(p.effective_start) <= on <= getdate(p.effective_end):
				return frappe.get_cached_doc("Force Majeure Pricing", p.name)
		return None

	return resolve


def fm_rate(pricing, item_code):
	"""The flat rate ``pricing`` sets for ``item_code``, or None when the item has no
	row or a zero rate -- a zero agreed rate is a data error, not an instruction to
	bill nothing, so the delivery stays on standard pricing."""
	for row in pricing.items:
		if row.item_code == item_code:
			return flt(row.override_rate) or None
	return None


def force_line(row, rate, pricing_name):
	"""Bill one invoice line at the Force Majeure rate and stamp it.

	``price_list_rate`` is set to the same figure and every discount field zeroed:
	ERPNext's totals pass re-derives ``rate`` as list minus discount, so writing
	only ``rate`` would be clobbered, and leaving the contract discount in place
	would discount the agreed price a second time."""
	row.price_list_rate = rate
	row.discount_percentage = 0
	row.discount_amount = 0
	row.margin_rate_or_amount = 0
	row.margin_type = ""
	row.rate = rate
	row.custom_force_majeure_pricing = pricing_name


def apply_force_majeure(doc, method=None):
	"""Sales Invoice ``validate`` -- the MANUAL path. Auto-invoicing splits its own
	lines in ``auto_invoicing._make_draft_invoice`` and is not affected here.

	Only lines traceable to a Delivery Note are decided, on that DN's posting
	date. A line with no delivery behind it is left alone: one invoice date is the
	wrong granularity for a rate that turns on the delivery date, and guessing
	would re-rate deliveries made outside the event. Auto-built lines carry no DN
	link, so this never disturbs the split they were created with."""
	if doc.doctype != "Sales Invoice" or doc.get("is_return"):
		return
	rows = [r for r in doc.get("items") or [] if r.get("delivery_note")]
	if not rows:
		return
	resolve = fm_resolver(doc.customer)
	if not resolve:
		return

	dn_dates = {}
	touched = False
	for row in rows:
		if row.delivery_note not in dn_dates:
			dn_dates[row.delivery_note] = frappe.db.get_value(
				"Delivery Note", row.delivery_note, "posting_date"
			)
		pricing = resolve(dn_dates[row.delivery_note])
		rate = fm_rate(pricing, row.item_code) if pricing else None
		if rate:
			force_line(row, rate, pricing.name)
			touched = True

	if touched:
		# doc_events validate runs after the controller's own totals pass, so the new
		# line rates need one more recalc to reach net_total / taxes.
		doc.calculate_taxes_and_totals()
