// Copyright (c) 2026, Fuelbuddy and contributors
// For license information, please see license.txt

// Ported from the "Create Finance Dosier" Client Script (code-first, no DB Client
// Scripts): replace the stock "Create" buttons with FuelBuddy's Quotation action.
// The Quotation button calls the whitelisted
// fuelbuddy_crm.quotation_link.create_quotation_from_opportunity and warns when a
// Quotation already exists instead of reporting a fresh creation.

frappe.ui.form.on("Opportunity", {
	refresh: function (frm) {
		if (frm.doc.__islocal) {
			return;
		}

		// add_custom_button dedupes by label, and ERPNext's stock controller already
		// added a "Quotation" button under "Create" during this same refresh. So we
		// must REMOVE the stock buttons FIRST and only THEN add our custom ones,
		// otherwise our custom Quotation handler silently fails to bind and the button
		// ends up removed. All adds run inside the same timeout, after the removals.
		setTimeout(function () {
			frm.remove_custom_button("Quotation", "Create");
			frm.remove_custom_button("Supplier Quotation", "Create");
			frm.remove_custom_button("Request For Quotation", "Create");

			frm.add_custom_button(
				__("Quotation"),
				function () {
					frappe.call({
						method: "fuelbuddy_crm.quotation_link.create_quotation_from_opportunity",
						args: { opportunity: frm.doc.name },
						freeze: true,
						freeze_message: __("Creating Quotation..."),
						callback: function (r) {
							var m = r.message || {};
							var q = m.created_quotation;
							if (!q) {
								return;
							}
							if (m.already_existed) {
								frappe.msgprint({
									title: __("Quotation already exists"),
									message: __("Quotation is already created"),
									indicator: "orange",
								});
							} else {
								frappe.show_alert({
									message: __("Quotation {0} created", [q]),
									indicator: "green",
								});
							}
							frm.reload_doc();
						},
					});
				},
				__("Create")
			);
		}, 10);
	},
});

// BUG-007: don't let an Opportunity be saved with a Contract Expiry / Valid Till that
// is before its transaction date. This is the immediate client-side guard; the
// authoritative check lives in fuelbuddy_crm.validations.validate_opportunity_valid_till.
frappe.ui.form.on("Opportunity", {
	validate: function (frm) {
		if (
			frm.doc.custom_contract_expiry &&
			frm.doc.transaction_date &&
			frappe.datetime.get_diff(frm.doc.custom_contract_expiry, frm.doc.transaction_date) < 0
		) {
			frappe.validated = false;
			frappe.msgprint({
				title: __("Invalid Valid Till date"),
				message: __("Valid till date cannot be before transaction date"),
				indicator: "red",
			});
		}
	},
});
