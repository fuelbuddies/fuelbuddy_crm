# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

"""Which Sales Orders a quantity-correction increase may spill onto (qty_correction._delta_candidates),
written from the business rules and not from the code.

The rules (owner, 12 Oct 2026):
  1. A spill onto another order follows the rule for a new Delivery Note: open orders only (To
     Deliver and Bill, To Deliver; never To Bill, Completed, On Hold or Closed), whatever the deal
     type; the date window is the Delivery Note's own posting date; a Fixed Quantity order has no
     end date; oldest-created first.
  2. The increase starts at the Delivery Note's last line's own order, then newer orders (as
     erp-functions updateDeliveryNote does).
  3. That own order comes first whatever its status: To Bill or Completed usually means this very
     Delivery Note used it up. A Closed or On Hold own order never gets here: the amend refuses it
     first (SO_CLOSED).
  4. An order takes the spill on its fuel line.

The fake ERP answers frappe.get_all the way Frappe v15 does (frappe/model/db_query.py
prepare_filter_condition): `!=` and `in` treat a missing value as '', a date compare treats a missing
date as 0001-01-01, `=` never matches a missing value, and a child-table filter returns the parent
once per matching child row; rows are frappe._dict, as get_all returns. No site and no database: run with the bench's python, e.g.

    python -m unittest fuelbuddy_crm.tests.test_amend_spill_candidates
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from frappe import _dict

from fuelbuddy_crm.api import qty_correction

FUEL = "FB/FL/00001"  # the production fuel item, as in qc_fixtures
SERVICE = "FB/SV/00001"
CUSTOMER = "CUST-1"
BILLING = "CUST-1-Billing"
POSTED = "2026-10-15"

DATE_FIELDS = {"transaction_date", "delivery_date"}


def _missing(field):
	return "0001-01-01" if field in DATE_FIELDS else ""


def _matches(value, field, op, expected):
	if op == "=":
		return value is not None and value == expected
	if op == "!=":
		return (value if value is not None else _missing(field)) != expected
	if op == "<=":
		return (value if value is not None else _missing(field)) <= expected
	if op == ">=":
		return (value if value is not None else _missing(field)) >= expected
	if op == "in":
		return (value if value is not None else _missing(field)) in expected
	raise AssertionError(f"fake ERP: operator {op} not modelled")


class FakeErp:
	def __init__(self, orders):
		self.orders = orders

	def get_all(self, doctype, filters=None, fields=None, order_by=None, limit_page_length=None):
		if doctype == "Sales Order":
			return self._orders(filters)
		if doctype == "Sales Order Item":
			return self._items(filters)
		raise AssertionError(f"fake ERP: unexpected get_all({doctype})")

	def _orders(self, filters):
		parent = [f for f in filters if len(f) == 3]
		child = [f for f in filters if len(f) == 4]
		rows = []
		for so in self.orders:
			if not all(_matches(so.get(field), field, op, value) for field, op, value in parent):
				continue
			if not child:
				rows.append(so)
				continue
			for item in so["items"]:
				if all(_matches(item.get(field), field, op, value) for _doctype, field, op, value in child):
					rows.append(so)
		# Frappe's default order (modified desc) is not creation order: the code must sort.
		rows.sort(key=lambda so: so["modified"], reverse=True)
		return [_dict(name=so["name"], creation=so["creation"], status=so["status"]) for so in rows]

	def _items(self, filters):
		so = next(so for so in self.orders if so["name"] == filters["parent"])
		items = [_dict(item) for item in so["items"]]
		if "name" in filters:
			items = [item for item in items if item["name"] == filters["name"]]
		return items


_seq = [0]


def line(**over):
	_seq[0] += 1
	return {
		"name": f"SOI-{_seq[0]}",
		"item_code": FUEL,
		"uom": "Litre",
		"conversion_factor": 1,
		"qty": 1000,
		"delivered_qty": 0,
		"custom_delivery_note_qty_in_draft": 0,
		**over,
	}


def order(name, deal_type="Long-term Contract", creation="2026-09-01 10:00:00", **over):
	return {
		"name": name,
		"customer": CUSTOMER,
		"customer_address": BILLING,
		"docstatus": 1,
		"status": "To Deliver and Bill",
		"custom_deal_type": deal_type,
		"transaction_date": "2026-10-01",
		"delivery_date": "2026-10-31",
		"creation": creation,
		"modified": str(99999999999999 - int("".join(ch for ch in creation if ch.isdigit()))),
		"items": [line()],
		**over,
	}


def delivery_note(*own_orders):
	"""A Delivery Note posted on POSTED whose lines sit on these orders' first lines."""
	return SimpleNamespace(
		customer=CUSTOMER,
		customer_address=BILLING,
		posting_date=POSTED,
		items=[
			SimpleNamespace(against_sales_order=so["name"], so_detail=so["items"][0]["name"]) for so in own_orders
		],
	)


def spill_candidates(orders, dn):
	with patch.object(qty_correction.frappe, "get_all", FakeErp(orders).get_all):
		return [(c["so"]["name"], c["soItem"]["name"]) for c in qty_correction._delta_candidates(dn)]


NOT_OPEN = ("To Bill", "Completed", "On Hold", "Closed")


class TestSpillOntoOtherOrders(unittest.TestCase):
	def test_only_open_orders_take_a_spill_whatever_the_deal_type(self):
		own = order("SO-OWN", creation="2026-08-01 10:00:00")
		others = [
			order(f"SO-{deal[:3].upper()}-{status.replace(' ', '')}", deal_type=deal, status=status)
			for deal in ("Long-term Contract", "Fixed Quantity")
			for status in NOT_OPEN
		]
		open_ltc = order("SO-OPEN-LTC", creation="2026-09-02 10:00:00", status="To Deliver")
		open_fq = order("SO-OPEN-FQ", deal_type="Fixed Quantity", creation="2026-09-03 10:00:00")
		got = spill_candidates([own, *others, open_ltc, open_fq], delivery_note(own))
		self.assertEqual(
			[name for name, _ in got],
			["SO-OWN", "SO-OPEN-LTC", "SO-OPEN-FQ"],
		)

	def test_a_fixed_quantity_order_past_its_end_date_takes_a_spill(self):
		own = order("SO-OWN", creation="2026-08-01 10:00:00")
		fq = order(
			"SO-FQ",
			deal_type="Fixed Quantity",
			creation="2026-09-01 10:00:00",
			transaction_date="2026-06-01",
			delivery_date="2026-06-30",
		)
		self.assertEqual([name for name, _ in spill_candidates([own, fq], delivery_note(own))], ["SO-OWN", "SO-FQ"])

	def test_the_date_window_is_the_delivery_note_s_own_posting_date(self):
		own = order("SO-OWN", creation="2026-08-01 10:00:00")
		ended_before = order("SO-ENDED", creation="2026-09-01 10:00:00", delivery_date="2026-10-14")
		ends_on_the_day = order("SO-LAST-DAY", creation="2026-09-02 10:00:00", delivery_date=POSTED)
		not_started = order("SO-LATER", creation="2026-09-03 10:00:00", transaction_date="2026-10-16")
		got = spill_candidates([own, ended_before, ends_on_the_day, not_started], delivery_note(own))
		self.assertEqual([name for name, _ in got], ["SO-OWN", "SO-LAST-DAY"])

	def test_a_spill_lands_on_the_order_s_fuel_line(self):
		own = order("SO-OWN", creation="2026-08-01 10:00:00")
		service = line(item_code=SERVICE)
		fuel = line()
		other = order("SO-OTHER", creation="2026-09-01 10:00:00", items=[service, fuel])
		self.assertEqual(spill_candidates([own, other], delivery_note(own))[1], ("SO-OTHER", fuel["name"]))


class TestTheDeliveryNoteSOwnOrder(unittest.TestCase):
	def test_the_increase_starts_at_the_last_line_s_own_order_then_newer_orders(self):
		older = order("SO-OLDER", creation="2026-07-01 10:00:00")
		own = order("SO-OWN", creation="2026-08-01 10:00:00")
		newer = order("SO-NEWER", creation="2026-09-01 10:00:00")
		got = spill_candidates([newer, older, own], delivery_note(own))
		self.assertEqual([name for name, _ in got], ["SO-OWN", "SO-NEWER"])

	def test_the_own_order_comes_first_even_when_to_bill_or_completed(self):
		for status in ("To Bill", "Completed"):
			with self.subTest(status):
				own = order("SO-OWN", creation="2026-08-01 10:00:00", status=status)
				newer = order("SO-NEWER", creation="2026-09-01 10:00:00")
				got = spill_candidates([own, newer], delivery_note(own))
				self.assertEqual(got, [("SO-OWN", own["items"][0]["name"]), ("SO-NEWER", newer["items"][0]["name"])])

	def test_the_own_order_is_used_on_the_delivery_note_s_own_line(self):
		own = order("SO-OWN", creation="2026-08-01 10:00:00", status="To Bill")
		self.assertEqual(spill_candidates([own], delivery_note(own)), [("SO-OWN", own["items"][0]["name"])])


if __name__ == "__main__":
	unittest.main()
