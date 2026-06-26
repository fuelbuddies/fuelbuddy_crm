app_name = "fuelbuddy_crm"
app_title = "Fuelbuddy CRM"
app_publisher = "Fuelbuddy"
app_description = "CRM customizations (Opportunity, Quotation, Lead, Customer)"
app_email = "shantanu.mishra@fuelbuddy.in"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "fuelbuddy_crm",
# 		"logo": "/assets/fuelbuddy_crm/logo.png",
# 		"title": "Fuelbuddy CRM",
# 		"route": "/fuelbuddy_crm",
# 		"has_permission": "fuelbuddy_crm.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/fuelbuddy_crm/css/fuelbuddy_crm.css"
# app_include_js = "/assets/fuelbuddy_crm/js/fuelbuddy_crm.js"

# include js, css files in header of web template
# web_include_css = "/assets/fuelbuddy_crm/css/fuelbuddy_crm.css"
# web_include_js = "/assets/fuelbuddy_crm/js/fuelbuddy_crm.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "fuelbuddy_crm/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# Opportunity form: replace the stock "Create" buttons with FuelBuddy's Quotation +
# Planning actions (the Quotation button creates a Draft Quotation from the Opportunity
# via fuelbuddy_crm.quotation_link.create_quotation_from_opportunity).
doctype_js = {
    "Opportunity": "public/js/opportunity.js",
    "Quotation": "public/js/quotation.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "fuelbuddy_crm/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "fuelbuddy_crm.utils.jinja_methods",
# 	"filters": "fuelbuddy_crm.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "fuelbuddy_crm.install.before_install"
# after_install = "fuelbuddy_crm.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "fuelbuddy_crm.uninstall.before_uninstall"
# after_uninstall = "fuelbuddy_crm.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "fuelbuddy_crm.utils.before_app_install"
# after_app_install = "fuelbuddy_crm.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "fuelbuddy_crm.utils.before_app_uninstall"
# after_app_uninstall = "fuelbuddy_crm.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "fuelbuddy_crm.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"fuelbuddy_crm.tasks.all"
# 	],
# 	"daily": [
# 		"fuelbuddy_crm.tasks.daily"
# 	],
# 	"hourly": [
# 		"fuelbuddy_crm.tasks.hourly"
# 	],
# 	"weekly": [
# 		"fuelbuddy_crm.tasks.weekly"
# 	],
# 	"monthly": [
# 		"fuelbuddy_crm.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "fuelbuddy_crm.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "fuelbuddy_crm.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# Add FuelBuddy connections (Finance Dossier, Business Documentation) to the
# Opportunity form's Connections tab. The override fn receives the base dashboard
# `data` dict and returns it augmented.
override_doctype_dashboards = {
    "Opportunity": "fuelbuddy_crm.dashboard_overrides.opportunity_dashboard",
}

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["fuelbuddy_crm.utils.before_request"]
# after_request = ["fuelbuddy_crm.utils.after_request"]

# Job Events
# ----------
# before_job = ["fuelbuddy_crm.utils.before_job"]
# after_job = ["fuelbuddy_crm.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"fuelbuddy_crm.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []


# Fixtures: all CRM customizations on Opportunity, Quotation, Lead, Customer.
# Sales Order carries only the read-only Discount tab custom fields (mirrored from
# the Quotation), so it is included in the Custom Field filter only -- not in the
# client/server-script or property-setter filters.
_CRM_DOCTYPES = ["Opportunity", "Quotation", "Lead", "Customer"]
# Custom Fields and Property Setters are also owned on Sales Order (the contract SO
# carries the CRM commercial fields and the form layout / naming-series for it).
_CUSTOM_FIELD_DOCTYPES = _CRM_DOCTYPES + ["Sales Order"]
# Property Setters also cover "Opportunity Item": its rate/qty are derived from the
# Opportunity Value section and are made read-only there (BUG-010).
_PROPERTY_SETTER_DOCTYPES = _CUSTOM_FIELD_DOCTYPES + ["Opportunity Item"]
fixtures = [
    {"dt": "Custom Field", "filters": [["dt", "in", _CUSTOM_FIELD_DOCTYPES]]},
    {"dt": "Property Setter", "filters": [["doc_type", "in", _PROPERTY_SETTER_DOCTYPES]]},
    {"dt": "Client Script", "filters": [["dt", "in", _CRM_DOCTYPES]]},
    {"dt": "Server Script", "filters": [["reference_doctype", "in", _CRM_DOCTYPES]]},
]

# Quotation lifecycle:
#  - after_insert: (1) give the Quotation its own 1:1 Discount (copied from the
#    Opportunity template), linked via Discount.quotation; (2) create the
#    Quotation's Draft Finance Dossier (1:1, finance_dossier_from="Quotation").
#  - on_submit: (1) start the contract Sales Order automation if the Opportunity
#    is ready (linked Quotation + Finance Dossier both submitted); (2) submit the
#    Quotation's Discount (atomic -- rolls the submit back if it fails).
#  - on_cancel: cancel the Quotation's Discount (atomic).
#
# Opportunity lifecycle (discount tab is the source of truth):
#  - validate: block a discount change once the Quotation / Finance Dossier is
#    submitted (the discount is then part of a signed contract).
#  - on_update: propagate a discount change down to the still-Draft Quotation, its
#    1:1 Discount and its Finance Dossier.
doc_events = {
    "Opportunity": {
        "validate": [
            # Reject bad inputs first so the user gets the precise message: negative
            # discounts (BUG-004) and an expired Valid Till (BUG-007).
            "fuelbuddy_crm.validations.validate_discount_values",
            "fuelbuddy_crm.validations.validate_opportunity_valid_till",
            "fuelbuddy_crm.discount_sync.guard_opportunity_discount",
        ],
        "on_update": "fuelbuddy_crm.discount_sync.propagate_opportunity_discount",
    },
    "Quotation": {
        # before_validate: default grand_total/base_grand_total so an item-less Quotation
        # can't crash ERPNext's set_payment_schedule() (BUG-001).
        "before_validate": "fuelbuddy_crm.quotation_link.guard_totals",
        "validate": [
            "fuelbuddy_crm.quotation_link.enforce_one_per_opportunity",
            # Reject negative discount inputs on the Quotation Discount tab (BUG-004).
            "fuelbuddy_crm.validations.validate_discount_values",
        ],
        "after_insert": [
            "fuelbuddy_crm.discount_sync.ensure_quotation_discount",
            "fuelbuddy_crm.finance_dossier.create_for_quotation",
        ],
        # Keep the Finance Dossier / Discount in sync with edits made directly on the
        # (still-Draft) Quotation (BUG-008).
        "on_update": "fuelbuddy_crm.discount_sync.propagate_quotation_discount",
        "on_submit": [
            "fuelbuddy_crm.sales_automation.on_quotation_submit",
            "fuelbuddy_crm.discount_sync.submit_quotation_discount",
        ],
        "on_update_after_submit": "fuelbuddy_crm.sales_automation.on_quotation_submit",
        "on_cancel": "fuelbuddy_crm.discount_sync.cancel_quotation_discount",
    },
    "Sales Order": {
        # Block manually creating a Sales Order outside the approval chain (BUG-012).
        # Automation / integrations (ignore_permissions) and Quotation-sourced SOs pass.
        "before_insert": "fuelbuddy_crm.validations.block_manual_sales_order",
    },
}

# Monthly: create each active contract's Sales Order for the current month
# (delivery date = last day of the month) until the contract expires.
scheduler_events = {
    "monthly": [
        "fuelbuddy_crm.sales_automation.generate_monthly_contract_sales_orders",
    ],
}
