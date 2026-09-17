# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""Force Majeure Pricing -- a customer's interim rates for a declared FM event.

This doc only *holds* the agreed rates and the window they apply to; the code that
actually re-rates Sales Orders / Delivery Notes / Sales Invoices lives in
``fuelbuddy_crm.force_majeure``. See that module for the four gates.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import formatdate, getdate


class ForceMajeurePricing(Document):
	def validate(self):
		self._validate_window()
		self._validate_items()
		self._validate_no_overlap()

	def before_update_after_submit(self):
		"""An Approved Pricing accepts exactly one change: ``effective_end`` (the only
		allow_on_submit field). This is how a running event is stopped early for the
		months not yet billed WITHOUT cancelling the Pricing -- which the invoices
		already billed under it forbid anyway. Frappe's own update-after-submit check
		rejects every other field.

		Who may: Frappe requires SUBMIT permission to update a submitted document
		(``Document._save`` -> ``check_permission("submit")``), and only System Manager
		and Force Majeure Manager hold it here -- a Force Majeure User is refused before
		this method runs, so there is no role check of our own.

		Rule: the new end can never fall before the latest invoice already connected
		to this Pricing, so a billed rate is never retroactively un-agreed. Extending is
		allowed subject to the same overlap guard as a new Pricing. Frappe does not run
		``validate`` on this path, so the window and overlap checks are repeated here."""
		before = self.get_doc_before_save()
		if not before or getdate(before.effective_end) == getdate(self.effective_end):
			return
		self._validate_window()
		self._validate_no_overlap()
		billed_upto = frappe.db.sql(
			"""
			select max(si.posting_date)
			from `tabSales Invoice` si
			join `tabSales Invoice Item` sii on sii.parent = si.name
			where sii.custom_force_majeure_pricing = %s and si.docstatus < 2
			""",
			self.name,
		)[0][0]
		if billed_upto and getdate(self.effective_end) < getdate(billed_upto):
			frappe.throw(
				_("Effective End cannot be before {0}: an invoice dated that day is already billed under this Pricing. Cancel that invoice first if the rate must be withdrawn from it.").format(
					frappe.bold(formatdate(billed_upto))
				)
			)

	def _validate_window(self):
		if getdate(self.effective_end) < getdate(self.effective_start):
			frappe.throw(_("Effective End cannot be before Effective Start."))

	def _validate_items(self):
		seen = set()
		for row in self.items:
			if row.item_code in seen:
				frappe.throw(
					_("Row {0}: {1} appears more than once; one row per item.").format(
						row.idx, row.item_code
					)
				)
			seen.add(row.item_code)
			# The form's link filter only narrows the picker; imports and API calls
			# bypass it, and this row sets a billing rate, so enforce it here too.
			if not frappe.db.get_value("Item", row.item_code, "is_stock_item"):
				frappe.throw(
					_("Row {0}: {1} is not a stock item (\"Maintain Stock\" is off); only fuel SKUs can carry a Force Majeure rate.").format(
						row.idx, row.item_code
					)
				)

	def _validate_no_overlap(self):
		"""Two APPROVED overrides covering the same customer+date would make the
		applied rate depend on row order, so refuse to save (and therefore to
		approve) anything that overlaps a live one. Drafts, rejected and cancelled
		docs never govern, so they never count as a clash -- the check bites at
		approval time, which is where it matters."""
		clash = frappe.db.sql(
			"""
			select name from `tabForce Majeure Pricing`
			where customer = %(customer)s and name != %(name)s and docstatus = 1
			  and effective_start <= %(end)s and effective_end >= %(start)s
			limit 1
			""",
			{
				"customer": self.customer,
				"name": self.name or "",
				"start": self.effective_start,
				"end": self.effective_end,
			},
		)
		if clash:
			frappe.throw(
				_("{0} already governs {1} over an overlapping period. Cancel it first.").format(
					frappe.bold(clash[0][0]), frappe.bold(self.customer)
				)
			)
