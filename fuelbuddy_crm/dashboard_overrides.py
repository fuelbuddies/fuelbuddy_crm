# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

from frappe import _


def opportunity_dashboard(data):
	"""Augment the Opportunity form's Connections tab with the FuelBuddy documents.

	Both target doctypes link back to the Opportunity via a Dynamic Link:
	  - Finance Dossier        -> finance_dossier_from == "Opportunity", id == <opp name>
	  - Business Documentation -> reference_doctype == "Opportunity", reference_name == <opp name>

	Registered via the `override_doctype_dashboards` hook; `data` is the base
	dashboard dict produced by erpnext's opportunity_dashboard.get_data().
	"""
	data = data or {}
	data.setdefault("transactions", [])
	data.setdefault("non_standard_fieldnames", {})

	# the dynamic-link field on each target that references the Opportunity name
	data["non_standard_fieldnames"]["Finance Dossier"] = "id"
	data["non_standard_fieldnames"]["Business Documentation"] = "reference_name"

	data["transactions"].append(
		{"label": _("FuelBuddy"), "items": ["Finance Dossier", "Business Documentation"]}
	)
	return data


def quotation_dashboard(data):
	"""Add the Finance Dossier connection to the Quotation form's Connections tab.

	Driven by the Quotation's own read-only link (custom_finance_dossier, kept in
	sync by finance_dossier.sync_source_reference) as an internal link -- the
	dashboard reads the field off the doc instead of searching Finance Dossiers.

	Registered via the `override_doctype_dashboards` hook; `data` is the base
	dashboard dict produced by erpnext's quotation_dashboard.get_data().
	"""
	data = data or {}
	data.setdefault("transactions", [])
	data.setdefault("internal_links", {})

	data["internal_links"]["Finance Dossier"] = "custom_finance_dossier"
	data["transactions"].append({"label": _("FuelBuddy"), "items": ["Finance Dossier"]})
	return data
