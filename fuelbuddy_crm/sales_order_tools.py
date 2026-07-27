# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""Sales Order Tools tab on Fuelbuddy Settings (DEV-5240 / DEV-5241).

- ``update_so_qty``: increase the quantity on a single-item Sales Order.
  Draft SOs are edited and saved; submitted SOs go through ERPNext's
  ``update_child_qty_rate`` so totals, taxes, Payment Schedule, reserved qty
  and the Version log stay correct.
- ``close_overdue_sales_orders``: bulk-Close Overdue SOs in a date range.
  "Overdue" is not a stored status - it mirrors ERPNext's list-view indicator:
  docstatus 1, per_delivered < 100, delivery_date < today, skip_delivery_note 0,
  status not in (Closed, On Hold, Completed). The range applies to
  ``transaction_date`` (per DEV-5241's fetch spec).
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, getdate, nowdate

FAT_FINGER_MULTIPLIER = 10
# sync close capped at this many SOs; larger runs go to the long queue
ASYNC_THRESHOLD = 200

BLOCKED_QTY_STATUSES = ("Closed", "Completed", "On Hold")


def _get_so_for_qty_update(sales_order):
	if not sales_order:
		frappe.throw(_("Sales Order is mandatory."))
	if not frappe.db.exists("Sales Order", sales_order):
		frappe.throw(_("Sales Order {0} does not exist.").format(sales_order))
	frappe.has_permission("Sales Order", "write", sales_order, throw=True)

	doc = frappe.get_doc("Sales Order", sales_order)
	if doc.docstatus == 2:
		frappe.throw(_("Cannot update a cancelled Sales Order."))
	if doc.status in BLOCKED_QTY_STATUSES:
		frappe.throw(_("Cannot update a {0} Sales Order.").format(doc.status))
	if len(doc.items) != 1:
		frappe.throw(
			_("Sales Order {0} has {1} item rows; only single-item Sales Orders can be updated here.").format(
				sales_order, len(doc.items)
			)
		)
	return doc


@frappe.whitelist()
def get_so_qty_context(sales_order):
	"""Autofill for the dialog: status, item and current qty of the selected SO."""
	doc = _get_so_for_qty_update(sales_order)
	item = doc.items[0]
	return {
		"status": f"{doc.status} ({'Draft' if doc.docstatus == 0 else 'Submitted'})",
		"item": item.item_code,
		"current_qty": item.qty,
		"delivered_qty": item.delivered_qty,
	}


@frappe.whitelist()
def update_so_qty(sales_order, new_qty, reason=None):
	doc = _get_so_for_qty_update(sales_order)
	item = doc.items[0]
	old_qty, new_qty = flt(item.qty), flt(new_qty)

	if new_qty <= 0:
		frappe.throw(_("Quantity must be greater than 0."))
	if new_qty < old_qty:
		frappe.throw(
			_(
				"Existing quantity on Sales Order {0} is {1}, which is already higher than the entered quantity {2}. Quantity can only be increased."
			).format(sales_order, old_qty, new_qty)
		)
	if new_qty == old_qty:
		frappe.throw(_("Nothing to update."))
	if new_qty < flt(item.delivered_qty):
		frappe.throw(
			_("New quantity {0} cannot be less than the already delivered quantity {1}.").format(
				new_qty, item.delivered_qty
			)
		)
	if old_qty and new_qty > old_qty * FAT_FINGER_MULTIPLIER:
		frappe.throw(
			_("New quantity {0} is more than {1}x the existing quantity {2}. Please re-check.").format(
				new_qty, FAT_FINGER_MULTIPLIER, old_qty
			)
		)

	if doc.docstatus == 0:
		item.qty = new_qty
		item.stock_qty = new_qty * flt(item.conversion_factor) or new_qty
		doc.save()
	else:
		from erpnext.controllers.accounts_controller import update_child_qty_rate

		update_child_qty_rate(
			"Sales Order",
			json.dumps(
				[
					{
						"docname": item.name,
						"item_code": item.item_code,
						"qty": new_qty,
						"rate": item.rate,
						"uom": item.uom,
						"conversion_factor": item.conversion_factor,
						"delivery_date": str(item.delivery_date) if item.delivery_date else None,
					}
				]
			),
			sales_order,
		)
		doc = frappe.get_doc("Sales Order", sales_order)

	comment = _("Quantity updated from {0} to {1} by {2}").format(old_qty, new_qty, frappe.session.user)
	if reason:
		comment += f"<br>{_('Reason')}: {reason}"
	doc.add_comment("Comment", comment)

	return {"old_qty": old_qty, "new_qty": new_qty, "grand_total": doc.grand_total, "status": doc.status}


def _validate_close_range(from_date, to_date):
	if not (from_date and to_date):
		frappe.throw(_("From Date and To Date are both mandatory."))
	from_date, to_date = getdate(from_date), getdate(to_date)
	if from_date > to_date:
		frappe.throw(_("From Date must be less than or equal to To Date."))
	if to_date > getdate(nowdate()):
		frappe.throw(_("To Date cannot be a future date."))
	max_days = cint(frappe.db.get_single_value("Fuelbuddy Settings", "so_close_max_range_days")) or 366
	if date_diff(to_date, from_date) > max_days:
		frappe.throw(_("Date range cannot exceed {0} days.").format(max_days))
	frappe.has_permission("Sales Order", "write", throw=True)
	return from_date, to_date


def _get_overdue_sos(from_date, to_date):
	return frappe.get_all(
		"Sales Order",
		filters={
			"docstatus": 1,
			"status": ["not in", ["Closed", "On Hold", "Completed"]],
			"skip_delivery_note": 0,
			"per_delivered": ["<", 100],
			"delivery_date": ["<", nowdate()],
			"transaction_date": ["between", [from_date, to_date]],
		},
		fields=["name", "customer", "transaction_date", "delivery_date", "grand_total", "status"],
		order_by="transaction_date asc, name asc",
	)


@frappe.whitelist()
def preview_overdue_sales_orders(from_date, to_date):
	from_date, to_date = _validate_close_range(from_date, to_date)
	return _get_overdue_sos(from_date, to_date)


@frappe.whitelist()
def close_overdue_sales_orders(from_date, to_date, reason=None):
	from_date, to_date = _validate_close_range(from_date, to_date)
	matched = [d.name for d in _get_overdue_sos(from_date, to_date)]
	if not matched:
		frappe.throw(_("No Overdue Sales Orders found between {0} and {1}.").format(from_date, to_date))

	if len(matched) > ASYNC_THRESHOLD:
		frappe.enqueue(
			"fuelbuddy_crm.sales_order_tools._close_sos",
			queue="long",
			names=matched,
			reason=reason,
			notify_user=frappe.session.user,
		)
		return {"queued": True, "matched": len(matched)}

	return _close_sos(matched, reason)


def _close_sos(names, reason=None, notify_user=None):
	closed, skipped, failed = [], [], []
	for name in names:
		frappe.db.savepoint("close_so")
		try:
			doc = frappe.get_doc("Sales Order", name)
			if doc.status == "Closed":
				skipped.append(name)
				continue
			doc.update_status("Closed")
			comment = _("Closed as Overdue via Fuelbuddy Settings by {0}").format(frappe.session.user)
			if reason:
				comment += f"<br>{_('Reason')}: {reason}"
			doc.add_comment("Comment", comment)
			closed.append(name)
		except Exception as e:
			frappe.db.rollback(save_point="close_so")
			failed.append({"name": name, "error": str(e)})

	summary = {
		"queued": False,
		"matched": len(names),
		"closed": len(closed),
		"skipped": skipped,
		"failed": failed,
	}
	assert summary["matched"] == summary["closed"] + len(skipped) + len(failed)

	if notify_user:
		frappe.publish_realtime(
			"msgprint",
			_("Close Overdue Sales Orders finished: {0} closed, {1} skipped, {2} failed.").format(
				len(closed), len(skipped), len(failed)
			),
			user=notify_user,
		)
	return summary
