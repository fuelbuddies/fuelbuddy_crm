// Copyright (c) 2026, Fuelbuddy and contributors
// For license information, please see license.txt

// Quotation form helpers (code-first, no DB Client Scripts):
//   - BUG-003: give the Quotation a clear, labelled path back to its parent Opportunity.
//     Opening a Quotation from the Opportunity otherwise drops the Opportunity context,
//     leaving users unsure how the two relate. A "View > Opportunity" button is used
//     rather than rewriting the breadcrumb trail (no stable app-level API for inserting
//     a parent document into breadcrumbs, and a wrong call can break the breadcrumb bar).
//   - BUG-005: guide the user to Save before Submit while there are unsaved changes.

frappe.ui.form.on("Quotation", {
	refresh: function (frm) {
		add_opportunity_navigation(frm);
		guide_save_before_submit(frm);
	},

	validate: function (frm) {
		guide_save_before_submit(frm);
	},
});

// A reliable, version-proof way back to the parent Opportunity: a "View > Opportunity"
// button on the Quotation form (BUG-003).
function add_opportunity_navigation(frm) {
	if (frm.is_new()) {
		return;
	}
	var opportunity = frm.doc.opportunity || frm.doc.custom_opportunity_from;
	if (!opportunity) {
		return;
	}
	frm.add_custom_button(
		__("Opportunity"),
		function () {
			frappe.set_route("Form", "Opportunity", opportunity);
		},
		__("View")
	);
}

// BUG-005: while the Quotation is new or has unsaved edits, make it explicit that it
// must be saved before it can be submitted. Frappe already hides the Submit action for
// unsaved docs; this adds the guidance the QA flagged as missing.
function guide_save_before_submit(frm) {
	if (frm.doc.docstatus === 0 && (frm.is_new() || frm.is_dirty())) {
		frm.set_intro(__("Save the Quotation before submitting."), "blue");
	} else {
		frm.set_intro("");
	}
}
