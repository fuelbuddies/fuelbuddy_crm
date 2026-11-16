# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""Retire the "Sales Order updated with Draft qty of delivery note" Server Script and
rebuild the reservation it was supposed to maintain.

`Sales Order Item.custom_delivery_note_qty_in_draft` is what the DN allocator subtracts
from a Sales Order's remaining qty (erp-functions `remainingLitres`). That Server Script
was its only writer, it was disabled, and even when enabled it ran on After Save only --
so it never released the reservation on DN cancel/delete. Both jobs now live in
fuelbuddy_crm.dn_validation.sync_draft_reservation (on_update/on_submit/on_cancel/on_trash).

Deleting the script stops it ever being re-enabled and double-writing; the backfill
re-derives every row from the live draft Delivery Notes."""

import frappe

_SCRIPT = "Sales Order updated with Draft qty of delivery note"


def execute():
	if frappe.db.exists("Server Script", _SCRIPT):
		frappe.delete_doc("Server Script", _SCRIPT, ignore_permissions=True, force=True)

	# Re-derive the reservation for every SO line in one pass: the sum of qty over draft
	# Delivery Note Items pointing at it, 0 where there are none (stale leftovers).
	frappe.db.sql(
		"""
		update `tabSales Order Item` soi
		left join (
			select dni.so_detail, sum(dni.qty) as qty
			from `tabDelivery Note Item` dni
			inner join `tabDelivery Note` dn on dn.name = dni.parent
			where dn.docstatus = 0
			group by dni.so_detail
		) d on d.so_detail = soi.name
		set soi.custom_delivery_note_qty_in_draft = coalesce(d.qty, 0)
		where soi.custom_delivery_note_qty_in_draft != coalesce(d.qty, 0)
		"""
	)
