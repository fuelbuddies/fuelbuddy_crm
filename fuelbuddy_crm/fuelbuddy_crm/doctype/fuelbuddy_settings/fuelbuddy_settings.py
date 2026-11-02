# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class FuelbuddySettings(Document):
	def validate(self):
		if cint(self.credit_overdue_grace_days) and cint(self.credit_overdue_grace_days) < 15:
			frappe.throw(_("Overdue Grace Days must be at least 15."))
