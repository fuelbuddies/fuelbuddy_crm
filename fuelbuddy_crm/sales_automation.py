# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

import frappe
from frappe.model.workflow import apply_workflow, get_workflow_name
from frappe.utils import add_months, flt, get_first_day, get_last_day, getdate, nowdate

# Sales Order workflow: "Approved" is the only docstatus=1 state, reached via the
# "Approve" transition. Contract SOs are created in "Pending" then approved+submitted.
SO_APPROVE_ACTION = "Approve"
CONTRACT_SO_QUEUE = "long"

# Each subsequent month's order quantity grows from the previous month's actual
# deliveries: next_qty = delivered_prev_month + delivered_prev_month * GROWTH = delivered * 1.25.
CONTRACT_QTY_GROWTH = 0.25

# Every SO-automation failure / timeout / no-SO outcome is written to the Error Log
# under a title starting with this prefix, so they can all be filtered in one place
# (List > Error Log, filter title "like Contract SO%").
SO_LOG_PREFIX = "Contract SO"


def _log_so(title, opportunity=None, quotation=None, detail=None, traceback=False):
	"""Record an SO-automation outcome in the Error Log. Used for failures, RQ
	timeouts and "expected an SO but produced none" cases so nothing fails
	silently. Never raises -- logging must not break the caller."""
	try:
		parts = []
		if opportunity:
			parts.append(f"Opportunity: {opportunity}")
		if quotation:
			parts.append(f"Quotation: {quotation}")
		if detail:
			parts.append(str(detail))
		if traceback:
			parts.append(frappe.get_traceback())
		message = "\n".join(parts) or title
		# Error Log title is capped at 140 chars.
		frappe.log_error(title=f"{SO_LOG_PREFIX}: {title}"[:140], message=message)
	except Exception:
		pass


def on_quotation_submit(doc, method=None):
	"""Quotation submit / update-after-submit hook -> start contract SO automation
	for the current month if the Opportunity is ready (Quotation + FD submitted)."""
	if getattr(doc, "custom_opportunity_from", None):
		create_sales_order_if_ready(doc.custom_opportunity_from)


@frappe.whitelist()
def create_sales_order_if_ready(opportunity):
	"""If the Opportunity's Quotation AND Finance Dossier are both submitted, kick
	off the current month's contract Sales Order (in the background). Idempotent.

	Never raises: this runs synchronously inside the Quotation / Finance Dossier
	submit, so any failure here is logged to the Error Log instead of bubbling up
	and rolling back (or 502-ing) the user's submit."""
	try:
		if not opportunity or not frappe.db.exists("Opportunity", opportunity):
			return None

		source, reason = _evaluate_contract_readiness(opportunity)
		if not source:
			# Not an error -- the Opportunity simply isn't ready yet (e.g. the
			# Finance Dossier or Quotation is still in draft). Log at info level
			# only, so the Error Log isn't flooded on every pre-FD submit.
			frappe.logger("fuelbuddy_crm").info(
				f"Contract SO not started for {opportunity}: {reason}"
			)
			return None

		# Run SO creation/submission in the background (as Administrator) so the
		# workflow "Approve" transition is permitted regardless of who submitted.
		frappe.enqueue(
			"fuelbuddy_crm.sales_automation.create_contract_month_so",
			queue=CONTRACT_SO_QUEUE,
			enqueue_after_commit=True,
			quotation=source,
			target_date=nowdate(),
			set_stage=True,
		)
		return source
	except Exception:
		# e.g. the redis queue is unreachable so enqueue() fails.
		_log_so("failed to queue SO creation", opportunity=opportunity, traceback=True)
		return None


def ready_contract_quotation(opportunity):
	"""Return the single source Quotation name when the Opportunity is ready:
	at least one submitted Quotation and at least one submitted Finance Dossier,
	with none of them still in draft. Otherwise None."""
	source, _reason = _evaluate_contract_readiness(opportunity)
	return source


def _evaluate_contract_readiness(opportunity):
	"""Return (source_quotation_or_None, reason). `reason` is a short human string
	explaining why it is not ready (used for logging) or "ready".

	The Finance Dossier is created from -- and linked 1:1 to -- the Quotation, so
	the contract source is the latest submitted Quotation whose Finance Dossier is
	also submitted."""
	quotations = frappe.get_all(
		"Quotation",
		filters={"custom_opportunity_from": opportunity, "docstatus": ["!=", 2]},
		fields=["name", "docstatus"],
	)
	if not quotations:
		return None, "no Quotation is linked to this Opportunity (custom_opportunity_from)"
	if any(q.docstatus != 1 for q in quotations):
		return None, "a linked Quotation is still in Draft"

	# all quotations are submitted here; newest first
	submitted = frappe.get_all(
		"Quotation",
		filters={"name": ["in", [q.name for q in quotations]], "docstatus": 1},
		order_by="creation desc",
		pluck="name",
	)
	dossier_status = {
		d.id: d.docstatus
		for d in frappe.get_all(
			"Finance Dossier",
			filters={
				"finance_dossier_from": "Quotation",
				"id": ["in", submitted],
				"docstatus": ["!=", 2],
			},
			fields=["id", "docstatus"],
		)
	}
	if not dossier_status:
		return None, "no Finance Dossier is linked to the Quotation (finance_dossier_from=Quotation/id)"

	# the source is the newest submitted Quotation whose Finance Dossier is submitted
	for q in submitted:
		if dossier_status.get(q) == 1:
			return q, "ready"
	return None, "a linked Finance Dossier is still in Draft"


@frappe.whitelist()
def create_contract_month_so(quotation, target_date=None, set_stage=False):
	"""Public entrypoint (also the enqueued job). Creates and submits one Sales
	Order for the month of `target_date` from a contract Quotation. Any failure or
	RQ timeout is recorded in the Error Log (title "Contract SO: creation failed")
	before being re-raised, so a background failure is never invisible."""
	try:
		return _create_contract_month_so(quotation, target_date=target_date, set_stage=set_stage)
	except Exception:
		_log_so("creation failed", quotation=quotation, traceback=True)
		raise


def _create_contract_month_so(quotation, target_date=None, set_stage=False):
	"""Idempotent per (quotation, month); stops once the contract has expired.
	Returns the SO name, or None when no SO is created (each None path is logged)."""
	# Background jobs run as the enqueuing user; the SO workflow "Approve"
	# transition needs System Manager, so act as Administrator.
	if frappe.session.user != "Administrator":
		frappe.set_user("Administrator")

	target_date = getdate(target_date or nowdate())
	month_start = get_first_day(target_date)
	month_end = get_last_day(target_date)

	qdoc = frappe.get_doc("Quotation", quotation)
	if qdoc.docstatus != 1:
		_log_so(
			"skipped: source Quotation is not submitted",
			quotation=quotation,
			detail=f"docstatus={qdoc.docstatus}",
		)
		return None

	# Stop once the contract has expired (no SO for months past expiry).
	expiry = qdoc.get("custom_contract_expiry")
	if expiry and getdate(expiry) < month_start:
		_log_so(
			"skipped: contract expired before this month",
			quotation=quotation,
			detail=f"custom_contract_expiry={expiry}, month_start={month_start}",
		)
		return None

	# Idempotent: one Sales Order per (quotation, month).
	existing = frappe.get_all(
		"Sales Order",
		filters={
			"custom_quotation": quotation,
			"docstatus": ["!=", 2],
			"delivery_date": ["between", [month_start, month_end]],
		},
		limit=1,
		pluck="name",
	)
	if existing:
		return existing[0]

	opportunity = qdoc.custom_opportunity_from

	# The first month's SO is mapped from the Quotation. Subsequent months are
	# cloned from that first SO, because make_sales_order maps only un-ordered
	# qty and returns no items once the Quotation is fully "Ordered".
	template = frappe.get_all(
		"Sales Order",
		filters={"custom_quotation": quotation, "docstatus": ["!=", 2]},
		order_by="creation asc",
		limit=1,
		pluck="name",
	)

	if template:
		# Subsequent months: order qty is driven by the PREVIOUS month's actual
		# deliveries +25% (next_qty = delivered_prev_month * (1 + CONTRACT_QTY_GROWTH)).
		# If the previous month had no SO or zero deliveries, skip this month entirely.
		prev_so = _previous_month_so(quotation, month_start)
		if not prev_so:
			_log_so(
				"skipped: no previous-month SO to grow this month's qty from",
				quotation=quotation,
				detail=f"month_start={month_start}",
			)
			return None
		delivered = _delivered_qty_by_item(prev_so)
		if not any(qty > 0 for qty in delivered.values()):
			_log_so(
				"skipped: previous month had zero deliveries",
				quotation=quotation,
				detail=f"prev_so={prev_so}",
			)
			return None

		so = frappe.copy_doc(frappe.get_doc("Sales Order", template[0]))
		kept = []
		for row in so.items:
			# each monthly SO is a standalone order; don't re-consume the Quotation's
			# ordered qty (keep only the first SO linked back to the Quotation).
			row.prevdoc_docname = None
			row.prevdoc_doctype = None
			row.quotation_item = None
			new_qty = flt(delivered.get(row.item_code, 0)) * (1 + CONTRACT_QTY_GROWTH)
			if new_qty > 0:
				row.qty = new_qty
				kept.append(row)
		so.items = kept
		for idx, row in enumerate(so.items, start=1):
			row.idx = idx
	else:
		# Sales Order needs a Customer. A Lead-based Quotation ALWAYS gets its own
		# freshly-created Customer (we never reuse an existing one for the Lead).
		new_customer = None
		if qdoc.quotation_to == "Lead":
			txn_ig = _transaction_item_group(opportunity, quotation)
			new_customer = ensure_customer_from_lead(qdoc.party_name, txn_ig, opportunity, quotation)

		from erpnext.selling.doctype.quotation.quotation import make_sales_order

		so = make_sales_order(quotation)

		# Force the SO onto the Customer we just created, in case make_sales_order
		# resolved an older Customer that shares this Lead.
		if new_customer:
			so.customer = new_customer
			so.customer_name = frappe.db.get_value("Customer", new_customer, "customer_name")

	so.custom_quotation = quotation
	so.transaction_date = nowdate()
	so.delivery_date = month_end

	# Mirror the Quotation's Discount tab onto the (read-only) Sales Order Discount
	# tab. The slab table is reset first so a cloned SO doesn't accumulate rows.
	so.custom_discount_method = qdoc.get("custom_discount_method")
	so.custom_discount_upto_date = qdoc.get("custom_discount_upto_date")
	so.custom_percentageper_litre = qdoc.get("custom_percentageper_litre")
	so.custom_percentage_value = qdoc.get("custom_percentage_value")
	so.custom_per_litre_value = qdoc.get("custom_per_litre_value")
	so.custom_max_discount_value = qdoc.get("custom_max_discount_value")
	so.set("custom_slab_discount", [])
	for s in (qdoc.get("custom_slab_discount") or []):
		so.append(
			"custom_slab_discount",
			{
				"p_or_v": s.p_or_v,
				"qty_limit": s.qty_limit,
				"discount_value": s.discount_value,
				"threshold_value": s.threshold_value,
				"limit": s.limit,
			},
		)

	# fill custom mandatory fields the standard mapper does not set
	so.custom_deal_type = qdoc.custom_deal_type or frappe.db.get_value(
		"Opportunity", opportunity, "custom_deal_type"
	)
	if not so.get("custom_transaction_type"):
		txn = frappe.db.get_value("Customer", so.customer, "custom_transaction_type")
		if not txn and so.items:
			txn = frappe.db.get_value("Item", so.items[0].item_code, "item_group")
		so.custom_transaction_type = txn
	if not so.get("custom_source_of_creation"):
		so.custom_source_of_creation = "ERP"
	if not so.get("custom_contract_type"):
		so.custom_contract_type = "FLEET"
	# Carry the agreed Payment Terms down the chain (Opportunity -> Quotation -> SO).
	if not so.get("custom_payment_terms"):
		so.custom_payment_terms = qdoc.get("custom_payment_terms") or frappe.db.get_value(
			"Opportunity", opportunity, "custom_payment_terms"
		)

	for row in so.items:
		row.delivery_date = month_end

	# Submit the SO. If Sales Order is under an active workflow, create it in the
	# initial "Pending" state and drive it to submitted via the "Approve"
	# transition. Otherwise (no workflow configured -- SOs are submitted directly
	# on this site, same as the manual "Create Sales Order" flow) just submit.
	if get_workflow_name("Sales Order"):
		so.workflow_state = "Pending"
		so.insert(ignore_permissions=True)
		apply_workflow(so, SO_APPROVE_ACTION)
	else:
		so.insert(ignore_permissions=True)
		so.submit()

	if set_stage and opportunity:
		frappe.db.set_value("Opportunity", opportunity, "sales_stage", "Sales Order Created")
	return so.name


def generate_monthly_contract_sales_orders():
	"""Monthly scheduler: for every active contract Quotation (submitted, FD ready,
	contract not yet expired), create this month's Sales Order. Idempotent."""
	today = getdate(nowdate())
	month_start = get_first_day(today)

	quotations = frappe.get_all(
		"Quotation",
		filters={"docstatus": 1, "custom_contract_expiry": [">=", month_start]},
		pluck="name",
	)
	for q in quotations:
		opportunity = frappe.db.get_value("Quotation", q, "custom_opportunity_from")
		if not opportunity:
			continue
		# Only the chosen source Quotation of a ready Opportunity drives generation.
		if ready_contract_quotation(opportunity) != q:
			continue
		try:
			_create_contract_month_so(q, today, set_stage=False)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			_log_so("monthly generation failed", quotation=q, traceback=True)


def _previous_month_so(quotation, month_start):
	"""Return this contract's submitted Sales Order for the month immediately before
	`month_start` (delivery_date in that month), or None if there isn't one."""
	prev = getdate(add_months(month_start, -1))
	rows = frappe.get_all(
		"Sales Order",
		filters={
			"custom_quotation": quotation,
			"docstatus": 1,
			"delivery_date": ["between", [get_first_day(prev), get_last_day(prev)]],
		},
		order_by="delivery_date desc",
		limit=1,
		pluck="name",
	)
	return rows[0] if rows else None


def _delivered_qty_by_item(so_name):
	"""Total delivered quantity per item_code on a Sales Order (net of returns, since
	ERPNext reduces delivered_qty for sales returns). {item_code: delivered_qty}."""
	out = {}
	for it in frappe.get_all(
		"Sales Order Item", filters={"parent": so_name}, fields=["item_code", "delivered_qty"]
	):
		out[it.item_code] = out.get(it.item_code, 0) + flt(it.delivered_qty)
	return out


def _transaction_item_group(opportunity, quotation):
	"""Resolve the transaction Item Group from the Opportunity product or the
	first quotation item (used to seed Customer.custom_transaction_type)."""
	txn_ig = None
	if opportunity:
		opp_product = frappe.db.get_value("Opportunity", opportunity, "custom_product")
		if opp_product:
			txn_ig = frappe.db.get_value("Item", opp_product, "item_group")
	if not txn_ig:
		first_item = frappe.get_all("Quotation Item", {"parent": quotation}, ["item_code"], limit=1)
		if first_item:
			txn_ig = frappe.db.get_value("Item", first_item[0].item_code, "item_group")
	return txn_ig


def ensure_customer_from_lead(lead_name, transaction_item_group=None, opportunity=None, quotation=None):
	"""Create a NEW Customer for a Lead-based Quotation so a Sales Order can be raised.

	A Quotation raised from a Lead ALWAYS gets its own freshly-created Customer --
	we intentionally do not reuse an existing Customer for the Lead. Copies VAT /
	Trade Licence from the Lead and the agreed Payment Terms down the chain
	(Opportunity -> Quotation -> Customer)."""
	if not lead_name or not frappe.db.exists("Lead", lead_name):
		return None
	lead = frappe.get_doc("Lead", lead_name)
	cust = frappe.new_doc("Customer")
	cust.customer_name = lead.company_name or lead.lead_name or lead_name
	cust.customer_type = lead.get("custom_customer_type") or "Company"
	cust.lead_name = lead_name
	group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	if group:
		cust.customer_group = group
	territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
	if territory:
		cust.territory = territory
	if transaction_item_group:
		cust.custom_transaction_type = transaction_item_group

	# Carry VAT / Trade Licence from the Lead onto the Customer.
	if lead.get("custom_vat_certificate"):
		cust.custom_vat_certificate = lead.custom_vat_certificate
	if lead.get("custom_trade_license"):
		cust.custom_trade_license = lead.custom_trade_license

	# Carry the agreed Payment Terms down the chain (Opportunity -> Quotation -> Customer).
	payment_terms = None
	if quotation:
		payment_terms = frappe.db.get_value("Quotation", quotation, "custom_payment_terms")
	if not payment_terms and opportunity:
		payment_terms = frappe.db.get_value("Opportunity", opportunity, "custom_payment_terms")
	if payment_terms:
		cust.custom_payment_terms = payment_terms

	cust.insert(ignore_permissions=True)
	return cust.name
