# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class ForceMajeureTrigger(Document):
	def validate(self):
		if self.global_end_date and getdate(self.global_end_date) < getdate(self.global_start_date):
			frappe.throw(_("FM Period End cannot be before FM Period Start."))
