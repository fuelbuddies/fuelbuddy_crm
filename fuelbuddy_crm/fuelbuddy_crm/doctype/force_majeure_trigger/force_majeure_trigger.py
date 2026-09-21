# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import formatdate, getdate

_FOREVER = "9999-12-31"  # an open-ended Trigger runs until it is cancelled


class ForceMajeureTrigger(Document):
	def validate(self):
		self._validate_window()
		self._validate_no_overlap()

	def _validate_window(self):
		if self.global_end_date and getdate(self.global_end_date) < getdate(self.global_start_date):
			frappe.throw(_("FM Period End cannot be before FM Period Start."))

	def _validate_no_overlap(self):
		"""One event at a time. A Trigger may not overlap any other DRAFT or SUBMITTED
		Trigger -- refused at save, not at submit, so a colliding draft never sits
		there waiting to be submitted. A blank end date counts as running forever.
		Cancelled Triggers are past events and never clash, so an amended Trigger
		(same dates as its cancelled original) saves normally."""
		clash = frappe.db.sql(
			"""
			select name, global_start_date, global_end_date from `tabForce Majeure Trigger`
			where name != %(name)s and docstatus < 2
			  and global_start_date <= %(end)s
			  and coalesce(global_end_date, %(forever)s) >= %(start)s
			limit 1
			""",
			{
				"name": self.name or "",
				"start": self.global_start_date,
				"end": self.global_end_date or _FOREVER,
				"forever": _FOREVER,
			},
			as_dict=True,
		)
		if clash:
			c = clash[0]
			frappe.throw(
				_("{0} already covers {1} to {2}. One Force Majeure event at a time: cancel it, end it earlier, or start this one after it ends.").format(
					frappe.bold(c.name),
					formatdate(c.global_start_date),
					formatdate(c.global_end_date) if c.global_end_date else _("open-ended"),
				)
			)
