"""Auto-Invoicing scheduler (IDEV-3000).

Daily job that generates **Draft** Sales Invoices from submitted Sales Orders,
driven by the SO's Invoicing Type:

  - **Single Invoice** -- one consolidated invoice per invoicing cycle. The cycle
    length comes from ``custom_invoicing_frequency`` (an "Invoice Days" record whose
    name is the number of days, e.g. "7"). An SO is due when `freq` days have passed
    since its last generated invoice (or since the SO's transaction date, for the
    first cycle).
  - **Split Invoice** -- one invoice per unique (``custom_department``,
    ``custom_billing_location``) pair across the SO's not-yet-invoiced Delivery
    Notes.

``custom_invoicing_frequency`` gates WHEN invoicing happens for both types;
``custom_invoicing_type`` only decides HOW the due DNs are grouped. An SO
without a frequency is skipped and logged.

Invoices are **built from the Sales Order** (party, prices and rates come from the
SO via the standard SO->SI mapper) while **quantities come from the Delivery
Notes**: ONE invoice row per SO line, its qty the sum of the group's DN
quantities delivered in the invoicing window. The delivered DN names are recorded
on the invoice's ``custom_dn_number`` (print) field and, for Split invoices, the
group's department / billing location go to ``custom_department`` /
``custom_location``.
This mirrors the manual prod flow (SI from SO + the "Auto Pick of DN at Sales
Invoice and Update of Qty" Server Script) -- but the scheduler computes the DN
quantities itself, per split group, so the invoice is inserted in a way that does
NOT trigger that script's date-range rollup (which is split-unaware and would
overwrite per-group quantities with the whole-range total).

The Quotation's discount (mirrored onto the SO's Discount tab by
``sales_automation``) is applied as a PER-LINE rate reduction: the line keeps its
catalog ``price_list_rate`` (from Item Price) and the discount formula computes
the actual ``rate`` off it, so the invoice shows "list -> discounted rate".

Idempotency is by INVOICING PERIOD, tracked on the Sales Order field
``custom_last_invoiced_upto`` (the end of the last period invoiced) -- not by any
DN<->invoice link nor a scan of the invoices. Each invoice covers a date window:
from the day after ``custom_last_invoiced_upto`` (or the SO's transaction date for
the first cycle) up to today. Quantity is the sum of Delivery Note deliveries
whose posting date falls in that window. The window always starts after the last
period, so DNs already invoiced are excluded by date, and the frequency gate
(today >= anchor + frequency) stops the SO being invoiced again before its next
cycle is due. After invoicing, the scheduler stamps ``custom_last_invoiced_upto``.
(Backdated DNs posted into an already-closed period are the known limitation of a
date-window model -- they fall before the next window and are not picked up.)

Failures are recorded as an ERPNext Issue with ``issue_type = "Invoicing"`` and
never block the rest of the batch.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, cstr, flt, getdate, nowdate, strip_html

ISSUE_TYPE = "Invoicing"
VALID_INVOICING_TYPES = ("Single Invoice", "Split Invoice")


def enqueue_generate_sales_invoices():
	"""Daily scheduler entry: hand the batch to the LONG queue with a 2-hour
	timeout. The scheduler's default queue caps jobs at 5 minutes, which a real
	invoicing run (hundreds of SOs, thousands of DNs) can outgrow. Deduplicated:
	if a previous run is still executing, today's enqueue is skipped."""
	frappe.enqueue(
		"fuelbuddy_crm.auto_invoicing.generate_sales_invoices",
		queue="long",
		timeout=7200,
		job_id="auto-invoicing-daily",
		deduplicate=True,
	)


def generate_sales_invoices():
	"""Daily scheduler entry point: invoice every Sales Order that is due.

	Two-level gate: "Enable Auto Invoicing (All Customers)" on Fuelbuddy Settings
	is the master switch (off = the scheduler does nothing); customers with
	"Disable Auto Invoicing" checked are excluded even while it is on."""
	all_customers = cint(
		frappe.db.get_single_value("Fuelbuddy Settings", "enable_auto_invoicing")
	)
	for so_name in _candidate_sales_orders():
		try:
			_invoice_sales_order(so_name, all_customers)
			frappe.db.commit()
		except Exception as e:
			frappe.db.rollback()
			# The exception's own message goes in the subject (quick triage from the
			# Issue list); the full traceback goes in the description.
			_log_invoicing_issue(
				so_name,
				_("Auto-invoicing failed for Sales Order {0}: {1}").format(
					so_name, strip_html(cstr(e))[:100]
				),
				frappe.get_traceback(),
			)


def _candidate_sales_orders():
	"""Sales Orders that have at least one submitted, non-return, non-Closed
	Delivery Note line -- the set worth evaluating today. Gates (submitted SO,
	customer flag, frequency, due window) are applied per SO downstream."""
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
	"""Generate the due Draft invoice(s) for one Sales Order, covering the DN
	deliveries in the current invoicing window."""
	so = frappe.get_doc("Sales Order", so_name)
	if so.docstatus != 1 or so.status in ("Closed", "On Hold"):
		return

	# Gate: the global switch must be on, and customers with "Disable Auto
	# Invoicing" checked are excluded. Skipping is silent (like "not due") --
	# an intentional configuration, not an error.
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
	from_date, to_date, freq_days, posting_date = window

	# DN deliveries for this SO whose posting date falls in the invoicing window.
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

	if freq_days == 0:
		# Frequency 0 = invoice per delivery: ONE invoice per Delivery Note
		# (all of that DN's item lines), regardless of Single/Split.
		by_dn = {}
		for dn in dns:
			by_dn.setdefault(dn.name, []).append(dn)
		groups = [by_dn[k] for k in sorted(by_dn)]
	elif invoicing_type == "Single Invoice":
		groups = [dns]
	else:
		# Split by the unique (department, billing location) pair. Keys are
		# normalised (trim + casefold) so "Finance " and "finance" don't split;
		# blank keys form their own bucket rather than being dropped (TC-07).
		grouped = {}
		for dn in dns:
			key = (
				(dn.custom_department or "").strip().casefold(),
				(dn.custom_billing_location or "").strip().casefold(),
			)
			grouped.setdefault(key, []).append(dn)
		groups = [grouped[k] for k in sorted(grouped)]

	for group in groups:
		_make_draft_invoice(so, group, from_date, to_date, posting_date)

	# Stamp the SO with the end of the period just invoiced. This single field --
	# not a scan of the Sales Invoices -- drives the next cycle's due-check and
	# window start (see _invoicing_window).
	frappe.db.set_value("Sales Order", so.name, "custom_last_invoiced_upto", to_date)


def _invoicing_window(so):
	"""Return ``(from_date, to_date, freq_days)`` for this SO's due invoicing
	period, or None if not due / frequency unset.

	Cycle state lives on the SO field ``custom_last_invoiced_upto`` (the end of the
	last period this scheduler invoiced). ``to_date`` is today; ``from_date`` is the
	day after that field (or the SO's transaction date for the first cycle). Due when
	today >= that anchor + frequency days.

	Frequency is a value, not a truthiness: ``0`` is valid and means "invoice per
	delivery" (due every day), while a *blank* frequency has no cycle -> log + skip.

	Returns ``(from_date, to_date, freq_days, posting_date)``. The DN window runs to
	today (``to_date``) so no delivery is missed; the invoice's ``posting_date`` is
	the frequency-meeting date (anchor + frequency), i.e. the period end -- today for
	frequency 0 (invoice-per-delivery)."""
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
	anchor = getdate(last_upto or so.transaction_date)
	today = getdate(nowdate())
	if today < getdate(add_days(anchor, freq_days)):
		return None

	from_date = getdate(add_days(last_upto, 1)) if last_upto else getdate(so.transaction_date)
	# Invoice is dated to the frequency-meeting date (period end); frequency 0
	# (invoice per delivery) posts on the run date.
	posting_date = today if freq_days == 0 else getdate(add_days(anchor, freq_days))
	return from_date, today, freq_days, posting_date


def _make_draft_invoice(so, dn_items, from_date, to_date, posting_date):
	"""Create ONE Draft Sales Invoice for a group of Delivery Note item rows.

	Built from the SO (standard SO->SI mapper: party, taxes, SO-line rates), with
	ONE row per SO line whose qty is the sum of the group's delivered DN
	quantities in the invoicing window. No DN<->invoice link is stored; the
	period ``custom_dn_from_date`` / ``custom_dn_to_date`` records the window
	that makes the next cycle start after it.
	"""
	from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

	si = make_sales_invoice(so.name, ignore_permissions=True)

	# Consolidate: the mapper made one row per SO line with qty = SO pending;
	# keep only lines the group actually delivered, qty = sum of DN quantities.
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

	# Date the invoice to the frequency-meeting date (period end), not the run date.
	si.set_posting_time = 1
	si.posting_date = posting_date

	dn_names = sorted({d.name for d in dn_items})
	si.custom_dn_number = ", ".join(dn_names)[:140]  # existing print field (Data)
	if (so.get("custom_invoicing_type") or "").strip() == "Split Invoice":
		si.custom_department = dn_items[0].custom_department
		si.custom_location = dn_items[0].custom_billing_location

	# Site-mandatory fields the mapper does not fill:
	# transaction type (same fallback chain as sales_automation) ...
	if not si.get("custom_transaction_type"):
		si.custom_transaction_type = (
			so.get("custom_transaction_type")
			or frappe.db.get_value("Customer", si.customer, "custom_transaction_type")
			or (si.items and frappe.db.get_value("Item", si.items[0].item_code, "item_group"))
		)
	# ... and a taxes template, when the SO carried none.
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
	si.flags.ignore_permissions = True
	# The invoicing-period dates are set AFTER insert (db_set fires no Before Save):
	# filling them at insert would trigger the live "Auto Pick of DN at Sales Invoice
	# and Update of Qty" Server Script, whose date-range rollup is split-unaware and
	# would overwrite the per-group quantities computed above. ignore_mandatory covers
	# the two date fields being briefly empty; every other known-mandatory field is
	# filled explicitly, and manual submit re-validates the lot. These dates also
	# anchor the NEXT cycle's window (from = this to_date + 1 day).
	# ponytail: drop this two-step insert once that Server Script is retired.
	# Always left in Draft for manual review -- never submitted by the scheduler.
	si.insert(ignore_permissions=True, ignore_mandatory=True)
	si.db_set({"custom_dn_from_date": from_date, "custom_dn_to_date": to_date})
	# The scheduler owns the authoritative period end (window end = to_date); set it
	# explicitly so it wins over the after_insert handler, which at insert time only
	# saw posting_date (custom_dn_to_date is db_set above, after the event fired).
	frappe.db.set_value("Sales Order", so.name, "custom_last_invoiced_upto", to_date)
	return si.name


def update_so_last_invoiced(doc, method=None):
	"""Sales Invoice after_insert / on_submit: advance each linked Sales Order's
	``custom_last_invoiced_upto`` to this invoice's period end (``custom_dn_to_date``
	if set, else ``posting_date``).

	This is what makes MANUAL invoices -- even a Draft -- shift the auto-invoicing
	cycle: once any invoice has billed up to a date, the scheduler's next window
	starts after it, so no delivery period is invoiced twice. Never moves the date
	backwards (a later invoice can only push it forward)."""
	upto = getdate(doc.get("custom_dn_to_date") or doc.get("posting_date") or nowdate())
	so_names = {r.get("sales_order") for r in (doc.get("items") or []) if r.get("sales_order")}
	for so in so_names:
		current = frappe.db.get_value("Sales Order", so, "custom_last_invoiced_upto")
		if not current or getdate(current) < upto:
			frappe.db.set_value(
				"Sales Order", so, "custom_last_invoiced_upto", upto, update_modified=False
			)


def _discount_source(so):
	"""Return the document whose Discount tab the auto-invoicing discount is read
	from, per the "Auto Invoicing Discount Source" setting on Fuelbuddy Settings:
	the SO's linked Quotation (default) or the Opportunity behind it.

	Opportunity, Quotation and Sales Order all carry the same ``custom_discount_*``
	fields and ``custom_slab_discount`` child table, so any of them reads uniformly.
	Falls back Quotation -> SO when the chosen source can't be resolved, so a
	discount is never silently lost."""
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
	if quotation and frappe.db.exists("Quotation", quotation):
		return frappe.get_doc("Quotation", quotation)
	return so


def _apply_quotation_discount(si, so):
	"""Apply the deal discount to the invoice as a PER-LINE rate reduction.

	The discount formula is read from the Quotation or the Opportunity, chosen by
	the "Auto Invoicing Discount Source" setting (see ``_discount_source``).

	The line keeps its catalog ``price_list_rate`` (from Item Price) and the discount
	formula computes the actual ``rate`` off that catalog price -- so the invoice reads
	"3.30 list -> 2.97 rate", with the discount visible as the gap on each line rather
	than a Net Total additional discount. VAT is charged on the discounted line amount.

	# ponytail: for Split invoices slabs/caps apply per split invoice, not per
	# SO cycle total -- revisit if the business wants cycle-level slab qty.
	"""
	src = _discount_source(so)
	method = (src.get("custom_discount_method") or "").strip()
	if not method:
		return

	upto = src.get("custom_discount_upto_date")
	if upto and getdate(si.posting_date or nowdate()) > getdate(upto):
		return

	# Discount is off the catalog list price; fall back to the mapped SO rate for
	# any line Item Price didn't feed a list price into.
	for i in si.items:
		if not flt(i.price_list_rate):
			i.price_list_rate = flt(i.rate)

	qty = sum(flt(i.qty) for i in si.items)
	pct = 0.0
	per_unit = 0.0  # discount amount per litre/unit
	slab_cap = 0.0

	if method == "Slab Discount":
		slab = _pick_slab(src.get("custom_slab_discount") or [], qty)
		if not slab:
			return
		if slab.p_or_v == "Percentage":
			pct = flt(slab.discount_value)
		else:  # Per Litre
			per_unit = flt(slab.discount_value)
		slab_cap = flt(slab.threshold_value)  # per-slab "Max Discount Value"
	elif src.get("custom_percentageper_litre") == "Percentage":
		pct = flt(src.get("custom_percentage_value"))
	else:  # Per Litre
		per_unit = flt(src.get("custom_per_litre_value"))

	# Total intended discount value across the invoice (to test caps against).
	list_total = sum(flt(i.price_list_rate) * flt(i.qty) for i in si.items)
	intended = list_total * pct / 100.0 if pct else per_unit * qty
	if intended <= 0:
		return

	caps = [c for c in (slab_cap, flt(src.get("custom_max_discount_value"))) if c > 0]
	cap = min(caps) if caps else None

	# Land the discount on the LINE. A clean, uncapped percentage is set natively as
	# a per-line % (invoice shows "list - 10%"); anything capped or per-litre becomes
	# a per-unit discount amount so rate = price_list_rate - discount_amount.
	# ponytail: the per-unit flattening below is exact for single-item (fuel)
	# invoices; distribute the cap per line by value if multi-item + capped appears.
	# rate is the money driver (server-side calculate does not derive rate from
	# discount_percentage -- that is a client-side step), so set rate explicitly
	# and fill discount_percentage / discount_amount to match for display.
	uncapped_pct = pct and not (cap and intended > cap)
	per_unit_eff = 0.0
	if not uncapped_pct:
		total = min(intended, cap) if cap else intended
		per_unit_eff = flt(total / qty, 6) if qty else 0
	for i in si.items:
		i.margin_type = ""
		list_rate = flt(i.price_list_rate)
		if uncapped_pct:
			i.discount_percentage = pct
			i.discount_amount = flt(list_rate * pct / 100.0, 6)
		else:
			i.discount_percentage = 0
			i.discount_amount = per_unit_eff
		i.rate = flt(list_rate - i.discount_amount, 6)

	# No Net Total additional discount -- the reduction lives on the lines.
	si.apply_discount_on = "Net Total"
	si.additional_discount_percentage = 0
	si.discount_amount = 0


def _pick_slab(slabs, qty):
	"""Return the slab row matching ``qty``: the first "Upper" row whose
	``qty_limit`` covers it, else the final "Lower" (open-ended) row.
	validate_discount guarantees the Upper..Upper..Lower ordering."""
	for row in slabs:
		if row.limit == "Upper" and qty <= flt(row.qty_limit):
			return row
	return slabs[-1] if slabs else None


def _log_invoicing_issue(so_name, subject, detail=None):
	"""Record a failure/skip as an ERPNext Issue (issue_type "Invoicing").

	Deduplicated per SO -- an open Invoicing Issue for the same SO is reused, so a
	persistently failing SO doesn't spawn one Issue per day. Never raises; falls
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
	"""Return the 'Invoicing' Issue Type, creating it once if absent (autoname=Prompt)."""
	if not frappe.db.exists("Issue Type", ISSUE_TYPE):
		it = frappe.new_doc("Issue Type")
		it.name = ISSUE_TYPE
		it.flags.ignore_permissions = True
		it.insert(ignore_permissions=True)
	return ISSUE_TYPE
