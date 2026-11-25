# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class FuelTank(Document):
	def validate(self):
		for field in ("tank_name", "tank_id", "vehicle_registration"):
			if value := self.get(field):
				self.set(field, value.strip())
