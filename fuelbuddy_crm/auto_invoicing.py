"""Auto-Invoicing scheduler (IDEV-3000).

Daily job that generates Draft Sales Invoices from submitted Sales Orders.
``custom_invoicing_type`` decides HOW deliveries are grouped (Single = one
consolidated invoice per cycle; Split = one per unique department / billing
location); ``custom_invoicing_frequency`` decides WHEN (an "Invoice Days"
record; 0 = invoice per Delivery Note; blank = skip + Issue).

Invoices are built from the SO (party / taxes / rates via the standard SO->SI
mapper) with quantities summed from the Delivery Notes in the invoicing window.
Idempotency is by period, tracked on ``custom_last_invoiced_upto``: each window
runs from the day after it (the SO transaction date for the first cycle) to
today -- to the previous month-end for frequency 30 (monthly) -- so
already-invoiced deliveries are excluded by date. The discount from
the Quotation / Opportunity is applied per line off the catalog price.

Failures are logged as an Issue (``issue_type = "Invoicing"``) without blocking
the batch.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, cstr, flt, get_first_day, getdate, nowdate, strip_html

ISSUE_TYPE = "Invoicing"
VALID_INVOICING_TYPES = ("Single Invoice", "Split Invoice")


def enqueue_generate_sales_invoices():
	"""Daily scheduler entry: run the batch on the LONG queue (2h timeout; the
	default queue caps at 5 min). Deduplicated, so a still-running batch is not
	launched twice."""
	frappe.enqueue(
		"fuelbuddy_crm.auto_invoicing.generate_sales_invoices",
		queue="long",
		timeout=7200,
		job_id="auto-invoicing-daily",
		deduplicate=True,
	)


def generate_sales_invoices():
	"""Invoice every due Sales Order. Master switch "Enable Auto Invoicing (All
	Customers)" off = no-op; customers with "Disable Auto Invoicing" are excluded."""
	all_customers = cint(
		frappe.db.get_single_value("Fuelbuddy Settings", "enable_auto_invoicing")
	)
	for so_name in _candidate_sales_orders():
		try:
			_invoice_sales_order(so_name, all_customers)
			frappe.db.commit()
		except Exception as e:
			frappe.db.rollback()
			_log_invoicing_issue(
				so_name,
				_("Auto-invoicing failed for Sales Order {0}: {1}").format(
					so_name, strip_html(cstr(e))[:100]
				),
				frappe.get_traceback(),
			)


def _candidate_sales_orders():
	"""Sales Orders with at least one submitted, non-return, non-Closed Delivery
	Note line. The remaining gates are applied per SO downstream."""
	return frappe.db.sql_list(
		"""
		select distinct dni.against_sales_order
		from `tabDelivery Note` dn
		join `tabDelivery Note Item` dni on dni.parent = dn.name
		where dn.docstatus = 1
			and ifnull(dn.is_return, 0) = 0
			and dn.status != 'Closed'
			and ifnull(dni.against_sales_order, '') != ''
		"""
	)


def _invoice_sales_order(so_name, all_customers=False):
	"""Generate the due Draft invoice(s) for one Sales Order."""
	# Cheap gate: only the fields the filters + window need; the full doc is
	# loaded later (below), once we know this SO is actually being invoiced.
	so = frappe.db.get_value(
		"Sales Order",
		so_name,
		[
			"name",
			"docstatus",
			"status",
			"customer",
			"custom_invoicing_type",
			"custom_invoicing_frequency",
			"custom_quotation",
			"custom_last_invoiced_upto",
			"transaction_date",
		],
		as_dict=True,
	)
	if not so or so.docstatus != 1 or so.status in ("Closed", "On Hold"):
		return

	# Silent skip (like "not due"): master switch off, or this customer opted out.
	if not all_customers or cint(
		frappe.db.get_value("Customer", so.customer, "custom_disable_auto_invoicing")
	):
		return

	invoicing_type = (so.get("custom_invoicing_type") or "").strip()
	if invoicing_type not in VALID_INVOICING_TYPES:
		_log_invoicing_issue(
			so_name,
			_("Sales Order {0} has blank/invalid Invoicing Type '{1}' -- skipped").format(
				so_name, invoicing_type
			),
		)
		return

	window = _invoicing_window(so)
	if not window:
		return
	from_date, to_date, freq_days = window

	dns = frappe.db.sql(
		"""
		select dn.name, dn.posting_date, dn.custom_department, dn.custom_billing_location,
			dni.so_detail, dni.item_code, dni.qty
		from `tabDelivery Note` dn
		join `tabDelivery Note Item` dni on dni.parent = dn.name
		where dn.docstatus = 1
			and ifnull(dn.is_return, 0) = 0
			and dn.status != 'Closed'
			and dni.against_sales_order = %s
			and dn.posting_date between %s and %s
		order by dn.posting_date, dn.name, dni.idx
		""",
		(so_name, from_date, to_date),
		as_dict=True,
	)
	if not dns:
		return

	# Due, and has deliveries -> load the full doc (needed by _make_draft_invoice).
	so = frappe.get_doc("Sales Order", so_name)

	if freq_days == 0:
		# freq 0 = invoice per delivery: one invoice per Delivery Note.
		by_dn = {}
		for dn in dns:
			by_dn.setdefault(dn.name, []).append(dn)
		groups = [by_dn[k] for k in sorted(by_dn)]
	elif invoicing_type == "Single Invoice":
		groups = [dns]
	else:
		# Split by unique (department, billing location), normalised so "Finance "
		# and "finance" don't split; blank keys get their own bucket, not dropped.
		grouped = {}
		for dn in dns:
			key = (
				(dn.custom_department or "").strip().casefold(),
				(dn.custom_billing_location or "").strip().casefold(),
			)
			grouped.setdefault(key, []).append(dn)
		groups = [grouped[k] for k in sorted(grouped)]

	for group in groups:
		_make_draft_invoice(so, group, from_date, to_date)

	# Period cursor that drives the next cycle's due-check and window start.
	frappe.db.set_value("Sales Order", so.name, "custom_last_invoiced_upto", to_date)


def _invoicing_window(so):
	"""Return ``(from_date, to_date, freq_days)`` for this SO's due period, or
	None if not due / frequency unset.

	Frequency is a value, not a truthiness: ``0`` is valid ("invoice per delivery",
	due every day); ``30`` means monthly -- only COMPLETED calendar months are
	billed: the run on the 1st takes the previous month's DNs, and the run day's
	own DNs go to the next cycle; a blank frequency has no cycle -> log + skip.
	Other frequencies are day counts with ``to_date`` today (so no delivery is
	missed)."""
	freq_raw = so.get("custom_invoicing_frequency")
	if freq_raw in (None, "") and so.get("custom_quotation"):
		freq_raw = frappe.db.get_value(
			"Quotation", so.custom_quotation, "custom_invoicing_frequency"
		)
	if freq_raw in (None, ""):
		_log_invoicing_issue(
			so.name,
			_("Sales Order {0} has no Invoicing Frequency -- skipped").format(so.name),
		)
		return None
	freq_days = cint(freq_raw)

	last_upto = so.get("custom_last_invoiced_upto")
	today = getdate(nowdate())
	from_date = getdate(add_days(last_upto, 1)) if last_upto else getdate(so.transaction_date)

	if freq_days == 30:
		# Monthly: window ends at the last day of the previous month. A month with
		# no DNs leaves the cursor put, so the next completed month sweeps it up.
		to_date = getdate(add_days(get_first_day(today), -1))
		if from_date > to_date:
			return None
		return from_date, to_date, freq_days

	anchor = getdate(last_upto or so.transaction_date)
	if today < getdate(add_days(anchor, freq_days)):
		return None
	return from_date, today, freq_days


def _make_draft_invoice(so, dn_items, from_date, to_date):
	"""Create ONE Draft Sales Invoice for a group of Delivery Note item rows: one
	row per SO line, qty = the group's delivered DN quantities. No DN<->invoice
	link is stored; ``custom_dn_from_date`` / ``custom_dn_to_date`` record the
	window that makes the next cycle start after it."""
	from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

	si = make_sales_invoice(so.name, ignore_permissions=True)

	# Keep only delivered lines; qty = sum of the group's DN quantities.
	qty_by_so_detail = {}
	for d in dn_items:
		qty_by_so_detail[d.so_detail] = qty_by_so_detail.get(d.so_detail, 0) + flt(d.qty)
	if unmatched := [d for d in dn_items if not any(r.so_detail == d.so_detail for r in si.items)]:
		frappe.throw(
			_("Delivery Note {0} row has no matching Sales Order line for item {1}").format(
				unmatched[0].name, unmatched[0].item_code
			)
		)
	rows = [r for r in si.items if r.so_detail in qty_by_so_detail]
	si.set("items", [])
	for row in rows:
		row.qty = qty_by_so_detail[row.so_detail]
		row.amount = row.base_amount = None
		si.append("items", row)

	if not si.get("items"):
		return None

	si.set_posting_time = 1
	si.posting_date = to_date

	dn_names = sorted({d.name for d in dn_items})
	si.custom_dn_number = ", ".join(dn_names)[:140]
	if (so.get("custom_invoicing_type") or "").strip() == "Split Invoice":
		si.custom_department = dn_items[0].custom_department
		si.custom_location = dn_items[0].custom_billing_location

	# Site-mandatory fields the mapper leaves blank: transaction type (same
	# fallback chain as sales_automation), then a default taxes template.
	if not si.get("custom_transaction_type"):
		si.custom_transaction_type = (
			so.get("custom_transaction_type")
			or frappe.db.get_value("Customer", si.customer, "custom_transaction_type")
			or (si.items and frappe.db.get_value("Item", si.items[0].item_code, "item_group"))
		)
	if not si.get("taxes_and_charges") and not si.get("taxes"):
		default_taxes = frappe.db.get_value(
			"Sales Taxes and Charges Template",
			{"company": si.company, "is_default": 1, "disabled": 0},
			"name",
		)
		if default_taxes:
			from erpnext.controllers.accounts_controller import get_taxes_and_charges

			si.taxes_and_charges = default_taxes
			for tax in get_taxes_and_charges("Sales Taxes and Charges Template", default_taxes):
				si.append("taxes", tax)

	_apply_quotation_discount(si, so)
	# Discount already applied in-process; the manual-SI before_save hook skips us.
	si.flags.fb_auto_invoicing = True
	si.flags.ignore_permissions = True
	# Set the period dates AFTER insert: filling them at insert fires the live
	# "Auto Pick of DN..." Server Script, whose split-unaware date-range rollup
	# would overwrite the per-group quantities. ignore_mandatory covers the two
	# briefly-empty date fields; manual submit re-validates. Left in Draft.
	# ponytail: drop this two-step insert once that Server Script is retired.
	si.insert(ignore_permissions=True, ignore_mandatory=True)
	si.db_set({"custom_dn_from_date": from_date, "custom_dn_to_date": to_date})
	# Scheduler owns the period end; set it explicitly (the after_insert handler
	# only saw posting_date, before custom_dn_to_date was db_set above).
	frappe.db.set_value("Sales Order", so.name, "custom_last_invoiced_upto", to_date)
	return si.name


def update_so_last_invoiced(doc, method=None):
	"""Sales Invoice after_insert / on_submit: advance each linked SO's
	``custom_last_invoiced_upto`` to this invoice's period end. This is what makes
	any invoice -- even a manual Draft -- shift the auto cycle so no period is
	billed twice. Only ever moves forward."""
	upto = getdate(doc.get("custom_dn_to_date") or doc.get("posting_date") or nowdate())
	so_names = {r.get("sales_order") for r in (doc.get("items") or []) if r.get("sales_order")}
	for so in so_names:
		current = frappe.db.get_value("Sales Order", so, "custom_last_invoiced_upto")
		if not current or getdate(current) < upto:
			frappe.db.set_value(
				"Sales Order", so, "custom_last_invoiced_upto", upto, update_modified=False
			)


def apply_manual_invoice_discount_save(doc, method=None):
	"""Sales Invoice ``before_save``: apply the deal discount to manually punched
	invoices. Runs after ``validate`` -- and Server Scripts (the live "Auto Pick of
	DN..." qty rewrite) fire on ``validate`` -- so the final quantities are seen."""
	_apply_manual_invoice_discount(doc)


def apply_manual_invoice_discount_submit(doc, method=None):
	"""Sales Invoice ``before_submit``: submit re-runs ``validate`` (the DN qty
	rewrite fires again) but not ``before_save``; re-apply so slab/cap discounts
	track the final quantities. Idempotent -- recomputed off price_list_rate."""
	_apply_manual_invoice_discount(doc)


def _apply_manual_invoice_discount(si):
	"""Apply ``_apply_quotation_discount`` to a manual SI linked to exactly one
	Sales Order. Scheduler-built invoices (flagged) and returns are skipped; SIs
	with no SO link are untouched. Multi-SO manual invoices are skipped -- group
	per SO if that ever appears."""
	if si.flags.get("fb_auto_invoicing") or cint(si.get("is_return")):
		return
	so_names = {r.get("sales_order") for r in (si.get("items") or []) if r.get("sales_order")}
	if len(so_names) != 1:
		return
	so = frappe.get_doc("Sales Order", next(iter(so_names)))
	if _apply_quotation_discount(si, so):
		# before_save/before_submit run after the controller's totals pass;
		# recalc so net_total / taxes follow the new line rates.
		si.calculate_taxes_and_totals()


# The engine reads the same logical fields off whichever doc the source setting
# resolves to; the standalone Discount doctype spells them differently.
_DISCOUNT_DOC_FIELDS = {
	"custom_discount_method": "discount_type",
	"custom_percentageper_litre": "p_or_v",
	"custom_percentage_value": "percentage_value",
	"custom_per_litre_value": "per_litre_value",
	"custom_max_discount_value": "threshold_value",
	"custom_discount_upto_date": "date",
	"custom_slab_discount": "slab_discount",
}


def _src_get(src, field):
	if src.doctype == "Discount":
		return src.get(_DISCOUNT_DOC_FIELDS[field])
	return src.get(field)


def _discount_source(so):
	"""The document the discount formula is read from, per the "Invoicing
	Discount Source" setting: source "Quotation" resolves the Discount doc
	linked 1:1 to the SO's Quotation (``Discount.quotation``); source
	"Opportunity" reads the Opportunity's own discount tab (the upload master).
	Falls back Quotation-Discount -> Quotation fields -> SO so a discount is
	never silently lost."""
	source = (
		frappe.db.get_single_value("Fuelbuddy Settings", "auto_invoicing_discount_source")
		or "Quotation"
	)
	quotation = so.get("custom_quotation")
	if source == "Opportunity":
		opp = quotation and frappe.db.get_value(
			"Quotation", quotation, "custom_opportunity_from"
		)
		if opp and frappe.db.exists("Opportunity", opp):
			return frappe.get_doc("Opportunity", opp)
	if quotation:
		from fuelbuddy_crm.discount_sync import get_quotation_discount

		dc = get_quotation_discount(quotation)
		if dc:
			return frappe.get_doc("Discount", dc)
	if quotation and frappe.db.exists("Quotation", quotation):
		return frappe.get_doc("Quotation", quotation)
	return so


def _apply_quotation_discount(si, so):
	"""Apply the deal discount as a PER-LINE rate reduction: the line keeps its
	catalog ``price_list_rate`` and the formula computes ``rate`` off it, so the
	invoice reads "3.30 list -> 2.97 rate" and VAT is charged on the discounted
	amount. Formula source is the Quotation or Opportunity (see ``_discount_source``).

	# ponytail: for Split invoices slabs/caps apply per split invoice, not per
	# SO cycle total -- revisit if the business wants cycle-level slab qty.
	"""
	src = _discount_source(so)
	method = (_src_get(src, "custom_discount_method") or "").strip()
	if not method:
		return

	upto = _src_get(src, "custom_discount_upto_date")
	if upto and getdate(si.posting_date or nowdate()) > getdate(upto):
		return

	# Discount is off the catalog list price; fall back to the SO rate if unset.
	for i in si.items:
		if not flt(i.price_list_rate):
			i.price_list_rate = flt(i.rate)

	qty = sum(flt(i.qty) for i in si.items)
	pct = 0.0
	per_unit = 0.0
	cap_total = 0.0     # slab threshold_value: caps the invoice-total discount
	cap_per_litre = 0.0  # Non-Slab Max Discount Value: PER-LITRE ceiling on the rate

	if method == "Slab Discount":
		slab = _pick_slab(_src_get(src, "custom_slab_discount") or [], qty)
		if not slab:
			return
		if slab.p_or_v == "Percentage":
			pct = flt(slab.discount_value)
			cap_total = flt(slab.threshold_value)
		else:
			per_unit = flt(slab.discount_value)
	else:
		# Non-Slab: normally the Percentage/Per Litre selector decides — but when
		# BOTH rates are non-zero they cap each other: the SMALLER effective
		# discount applies, i.e. the higher after-discount rate wins (business
		# rule, 31 Jul 2026). Pure RATE comparison — the max stays out of it.
		pct_val = flt(_src_get(src, "custom_percentage_value"))
		per_l_val = flt(_src_get(src, "custom_per_litre_value"))
		list_total = sum(flt(i.price_list_rate) * flt(i.qty) for i in si.items)
		if pct_val and per_l_val:
			use_pct = list_total * pct_val / 100.0 <= per_l_val * qty
		else:
			# One (or both) rate is zero: apply the non-zero one — the
			# Percentage/Per Litre selector is display-only and can't zero out
			# a filled rate. Both zero falls through to intended<=0 (no-op).
			use_pct = bool(pct_val)
		if use_pct:
			pct = pct_val
			# Business fills Max Discount Value at per-litre scale (0.1, 0.22,
			# 0.3): it bounds the discount RATE, never the invoice total — an
			# 11% deal capped at 0.30 means "at most 0.30 AED off per litre".
			cap_per_litre = flt(_src_get(src, "custom_max_discount_value"))
		else:
			per_unit = per_l_val

	list_total = sum(flt(i.price_list_rate) * flt(i.qty) for i in si.items)
	intended = list_total * pct / 100.0 if pct else per_unit * qty
	if intended <= 0:
		return

	if cap_total and intended > cap_total:
		intended = cap_total
	per_unit_rate = intended / qty if qty else 0
	if cap_per_litre and per_unit_rate > cap_per_litre:
		per_unit_rate = cap_per_litre
	capped = pct and per_unit_rate < (list_total * pct / 100.0 / qty) if qty else False

	# Land it on the line: a clean uncapped % goes in natively; anything capped or
	# per-litre becomes a per-unit discount_amount. rate is the money driver
	# (server calc won't derive it from discount_percentage), so set rate
	# explicitly and fill discount_percentage / amount to match for display.
	# ponytail: per-unit flattening is exact for single-item (fuel) invoices;
	# distribute the cap per line by value if multi-item + capped appears.
	uncapped_pct = pct and not capped
	per_unit_eff = per_unit_rate
	for i in si.items:
		i.margin_type = ""
		list_rate = flt(i.price_list_rate)
		if uncapped_pct:
			i.discount_percentage = pct
			i.discount_amount = list_rate * pct / 100.0
		else:
			i.discount_percentage = 0
			i.discount_amount = per_unit_eff
		# No rounding here — raw floats; field precision is Frappe's business.
		i.rate = list_rate - i.discount_amount

	# No Net Total additional discount -- the reduction lives on the lines.
	si.apply_discount_on = "Net Total"
	si.additional_discount_percentage = 0
	si.discount_amount = 0
	return True


def _pick_slab(slabs, qty):
	"""The slab matching ``qty``: the first "Upper" row whose ``qty_limit`` covers
	it, else the final "Lower" (open-ended) row. validate_discount guarantees the
	Upper..Upper..Lower ordering."""
	for row in slabs:
		if row.limit == "Upper" and qty <= flt(row.qty_limit):
			return row
	return slabs[-1] if slabs else None


def _log_invoicing_issue(so_name, subject, detail=None):
	"""Record a failure/skip as an Issue (issue_type "Invoicing"), deduplicated per
	SO so a persistently failing SO doesn't spawn one per day. Never raises; falls
	back to the Error Log if the Issue itself cannot be created."""
	try:
		if frappe.get_all(
			"Issue",
			filters={
				"issue_type": ISSUE_TYPE,
				"status": ["not in", ["Closed", "Resolved"]],
				"subject": ["like", f"Invoicing: {so_name}%"],
			},
			limit=1,
		):
			return
		issue = frappe.new_doc("Issue")
		issue.subject = f"Invoicing: {so_name}: {subject}"[:140]
		issue.issue_type = _ensure_issue_type()
		issue.description = "\n\n".join(filter(None, [subject, detail]))
		issue.customer = frappe.db.get_value("Sales Order", so_name, "customer")
		issue.flags.ignore_permissions = True
		issue.insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error(
			title=f"Auto-Invoicing: {subject}"[:140],
			message="\n\n".join(filter(None, [subject, detail, frappe.get_traceback()])),
		)


def _ensure_issue_type():
	"""Return the 'Invoicing' Issue Type, creating it once if absent."""
	if not frappe.db.exists("Issue Type", ISSUE_TYPE):
		it = frappe.new_doc("Issue Type")
		it.name = ISSUE_TYPE
		it.flags.ignore_permissions = True
		it.insert(ignore_permissions=True)
	return ISSUE_TYPE
