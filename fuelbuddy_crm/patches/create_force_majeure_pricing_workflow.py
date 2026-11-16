# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""Approval workflow for Force Majeure Pricing (IDEV-3129).

	Draft --Submit for Approval (User)--> Pending --Approve (Manager)--> Approved [docstatus 1]
	                                              --Reject  (Manager)--> Rejected --Resubmit (User)--> Pending

Created once by patch rather than shipped as a fixture: fixtures re-import on every
migrate and would silently overwrite any tweak ops makes to the transitions later.
Frappe's Workflow.on_update adds the ``workflow_state`` Custom Field itself.
Reuses the stock "Pending" / "Approved" / "Rejected" states and "Approve" / "Reject"
actions; only "Draft" and the two custom actions are created."""

import frappe

WORKFLOW = "Force Majeure Pricing Approval"
MANAGER = "Force Majeure Manager"
USER = "Force Majeure User"


def _ensure(doctype, name, **values):
	if not frappe.db.exists(doctype, name):
		frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)


def execute():
	_ensure("Workflow State", "Draft", workflow_state_name="Draft", style="")
	_ensure("Workflow Action Master", "Submit for Approval", workflow_action_name="Submit for Approval")
	_ensure("Workflow Action Master", "Resubmit", workflow_action_name="Resubmit")

	if frappe.db.exists("Workflow", WORKFLOW):
		return

	frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_name": WORKFLOW,
			"document_type": "Force Majeure Pricing",
			"workflow_state_field": "workflow_state",
			"is_active": 1,
			"send_email_alert": 0,
			"override_status": 0,
			"states": [
				{"state": "Draft", "doc_status": "0", "allow_edit": USER},
				{"state": "Pending", "doc_status": "0", "allow_edit": MANAGER},
				{"state": "Approved", "doc_status": "1", "allow_edit": MANAGER},
				{"state": "Rejected", "doc_status": "0", "allow_edit": USER},
			],
			"transitions": [
				{"state": "Draft", "action": "Submit for Approval", "next_state": "Pending", "allowed": USER, "allow_self_approval": 1},
				{"state": "Pending", "action": "Approve", "next_state": "Approved", "allowed": MANAGER, "allow_self_approval": 1},
				{"state": "Pending", "action": "Reject", "next_state": "Rejected", "allowed": MANAGER, "allow_self_approval": 1},
				{"state": "Rejected", "action": "Resubmit", "next_state": "Pending", "allowed": USER, "allow_self_approval": 1},
			],
		}
	).insert(ignore_permissions=True)
