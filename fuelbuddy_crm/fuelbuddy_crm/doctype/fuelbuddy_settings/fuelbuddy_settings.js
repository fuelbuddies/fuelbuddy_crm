// Copyright (c) 2026, Fuelbuddy and contributors
// For license information, please see license.txt

// Sales Order Tools tab (DEV-5240 / DEV-5241). Buttons open dialogs; all
// validation and the actual updates live in fuelbuddy_crm.sales_order_tools.

frappe.ui.form.on("Fuelbuddy Settings", {
	update_so_qty_button() {
		show_update_so_qty_dialog();
	},
	close_overdue_so_button() {
		show_close_overdue_dialog();
	},
});

function show_update_so_qty_dialog() {
	const d = new frappe.ui.Dialog({
		title: __("Update Sales Order Quantity"),
		fields: [
			{
				fieldname: "sales_order",
				fieldtype: "Link",
				label: __("Sales Order"),
				options: "Sales Order",
				reqd: 1,
				get_query: () => ({
					filters: {
						docstatus: ["<", 2],
						status: ["not in", ["Closed", "Completed", "On Hold"]],
					},
				}),
				onchange() {
					const so = d.get_value("sales_order");
					if (!so) return;
					frappe.call({
						method: "fuelbuddy_crm.sales_order_tools.get_so_qty_context",
						args: { sales_order: so },
						callback(r) {
							d.set_values({
								so_status: r.message.status,
								item: r.message.item,
								current_qty: r.message.current_qty,
							});
						},
					});
				},
			},
			{ fieldname: "so_status", fieldtype: "Data", label: __("Status"), read_only: 1 },
			{ fieldname: "item", fieldtype: "Data", label: __("Item"), read_only: 1 },
			{ fieldname: "current_qty", fieldtype: "Float", label: __("Current Quantity"), read_only: 1 },
			{ fieldname: "new_qty", fieldtype: "Float", label: __("New Quantity"), reqd: 1 },
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason / Remarks") },
		],
		primary_action_label: __("Update Quantity"),
		primary_action(values) {
			frappe.confirm(
				__("Update quantity on {0} from {1} to {2}?", [
					values.sales_order.bold(),
					String(values.current_qty).bold(),
					String(values.new_qty).bold(),
				]),
				() => {
					frappe.call({
						method: "fuelbuddy_crm.sales_order_tools.update_so_qty",
						args: {
							sales_order: values.sales_order,
							new_qty: values.new_qty,
							reason: values.reason,
						},
						freeze: true,
						callback(r) {
							d.hide();
							frappe.msgprint({
								title: __("Quantity Updated"),
								indicator: "green",
								message: __("{0}: quantity {1} → {2}. New Grand Total: {3}. Status: {4}.", [
									values.sales_order,
									r.message.old_qty,
									r.message.new_qty,
									format_currency(r.message.grand_total),
									r.message.status,
								]),
							});
						},
					});
				}
			);
		},
	});
	d.show();
}

function show_close_overdue_dialog() {
	const d = new frappe.ui.Dialog({
		title: __("Close Overdue Sales Orders"),
		fields: [
			{ fieldname: "from_date", fieldtype: "Date", label: __("From Date"), reqd: 1 },
			{ fieldname: "col", fieldtype: "Column Break" },
			{ fieldname: "to_date", fieldtype: "Date", label: __("To Date"), reqd: 1 },
			{ fieldname: "sec", fieldtype: "Section Break" },
			{
				fieldname: "preview",
				fieldtype: "Button",
				label: __("Preview"),
				click() {
					const { from_date, to_date } = d.get_values();
					if (!from_date || !to_date) return;
					frappe.call({
						method: "fuelbuddy_crm.sales_order_tools.preview_overdue_sales_orders",
						args: { from_date, to_date },
						callback(r) {
							const rows = r.message || [];
							const list = rows
								.map(
									(so) =>
										`<tr><td>${frappe.utils.get_form_link("Sales Order", so.name, true)}</td>
										<td>${so.customer}</td><td>${so.transaction_date}</td>
										<td>${so.delivery_date}</td><td>${so.status}</td></tr>`
								)
								.join("");
							d.get_field("preview_html").$wrapper.html(
								rows.length
									? `<p><b>${__("{0} Overdue Sales Order(s) will be closed.", [rows.length])}</b></p>
									<div style="max-height:200px;overflow-y:auto"><table class="table table-bordered">
									<thead><tr><th>${__("Sales Order")}</th><th>${__("Customer")}</th>
									<th>${__("SO Date")}</th><th>${__("Delivery Date")}</th><th>${__("Status")}</th></tr></thead>
									<tbody>${list}</tbody></table></div>`
									: `<p>${__("No Overdue Sales Orders found in this range.")}</p>`
							);
						},
					});
				},
			},
			{ fieldname: "preview_html", fieldtype: "HTML" },
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason / Remarks") },
		],
		primary_action_label: __("Close Overdue Sales Orders"),
		primary_action(values) {
			frappe.call({
				method: "fuelbuddy_crm.sales_order_tools.preview_overdue_sales_orders",
				args: { from_date: values.from_date, to_date: values.to_date },
				callback(r) {
					const count = (r.message || []).length;
					if (!count) {
						frappe.msgprint(
							__("No Overdue Sales Orders found between {0} and {1}.", [
								values.from_date,
								values.to_date,
							])
						);
						return;
					}
					frappe.confirm(
						__("This will mark {0} Overdue Sales Order(s) as Closed. Continue?", [
							String(count).bold(),
						]),
						() => {
							frappe.call({
								method: "fuelbuddy_crm.sales_order_tools.close_overdue_sales_orders",
								args: {
									from_date: values.from_date,
									to_date: values.to_date,
									reason: values.reason,
								},
								freeze: true,
								callback(res) {
									d.hide();
									const s = res.message;
									if (s.queued) {
										frappe.msgprint(
											__(
												"{0} Sales Orders queued for closing in the background. You will be notified on completion.",
												[s.matched]
											)
										);
										return;
									}
									let msg = __("Matched: {0}, Closed: {1}, Skipped: {2}, Failed: {3}", [
										s.matched,
										s.closed,
										s.skipped.length,
										s.failed.length,
									]);
									if (s.skipped.length)
										msg += `<br>${__("Skipped (already Closed)")}: ${s.skipped.join(", ")}`;
									if (s.failed.length)
										msg += `<br>${__("Failed")}: ${s.failed
											.map((f) => `${f.name} (${f.error})`)
											.join("<br>")}`;
									frappe.msgprint({
										title: __("Close Overdue Sales Orders"),
										indicator: s.failed.length ? "orange" : "green",
										message: msg,
									});
								},
							});
						}
					);
				},
			});
		},
	});
	d.show();
}
