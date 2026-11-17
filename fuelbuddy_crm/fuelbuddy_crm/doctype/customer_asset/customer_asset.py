# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

# A customer's asset (vehicle, tank, generator...) that fuel is delivered to. Made on production as a
# custom DocType (Selling, 2024) and owned by this app since: customer_asset.json is that DocType as
# production has it, so the first migrate rewrites only its metadata and leaves the table as it is.

from frappe.model.document import Document


class CustomerAsset(Document):
	pass
