# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""Keep a Quotation 1:1 with its Opportunity.

A Quotation carries two Opportunity links: the standard ``opportunity`` (which
drives every ``fetch_from`` on the Quotation's custom fields) and the custom
``custom_opportunity_from`` (which drives the Discount / Finance Dossier / Sales
Order automation). This module keeps the two in lock-step so they can never
diverge, and enforces at most one non-cancelled Quotation per Opportunity.
"""

import frappe
from frappe import _


def enforce_one_per_opportunity(doc, method=None):
	"""Quotation ``validate`` -> sync the two Opportunity links and enforce that an
	Opportunity has at most one non-cancelled Quotation."""
	# Whichever link the Quotation was created with wins; mirror it onto the other
	# so fetch_from (uses `opportunity`) and the automation (uses
	# `custom_opportunity_from`) always agree.
	opportunity = doc.get("custom_opportunity_from") or doc.get("opportunity")
	if not opportunity:
		return
	doc.custom_opportunity_from = opportunity
	doc.opportunity = opportunity

	# At most one non-cancelled Quotation per Opportunity.
	duplicate = frappe.db.get_value(
		"Quotation",
		{
			"custom_opportunity_from": opportunity,
			"docstatus": ["<", 2],
			"name": ["!=", doc.name or ""],
		},
		"name",
	)
	if duplicate:
		frappe.throw(
			_(
				"Opportunity {0} already has Quotation {1}. Only one Quotation is allowed per Opportunity."
			).format(opportunity, duplicate)
		)
