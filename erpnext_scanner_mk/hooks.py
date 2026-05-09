app_name = "erpnext_scanner_mk"
app_title = "ERPNext Scanner MK"
app_publisher = "Tik13 GmbH"
app_description = "something"
app_email = "mike@tik13.org"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
add_to_apps_screen = [
	{
		"name": "erpnext_scanner_mk",
		"logo": "/assets/erpnext_scanner_mk/images/scanner-mk-icon.svg",
		"title": "ERPNext Scanner MK",
		"route": "/app/invoice-automation"
	}
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/erpnext_scanner_mk/css/scanner_mk.css"
# app_include_js = "/assets/erpnext_scanner_mk/js/scanner_mk.js"

# include js, css files in header of web template
# web_include_css = "/assets/erpnext_scanner_mk/css/scanner_mk.css"
# web_include_js = "/assets/erpnext_scanner_mk/js/scanner_mk.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "erpnext_scanner_mk/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
	"Invoice Intake Log": "erpnext_scanner_mk/erpnext_scanner_mk/erpnext_scanner_mk/doctype/invoice_intake_log/invoice_intake_log.js"
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "erpnext_scanner_mk/public/icons.svg"

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

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "erpnext_scanner_mk.utils.jinja_methods",
# 	"filters": "erpnext_scanner_mk.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "erpnext_scanner_mk.install.before_install"
# after_install = "erpnext_scanner_mk.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "erpnext_scanner_mk.uninstall.before_uninstall"
# after_uninstall = "erpnext_scanner_mk.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "erpnext_scanner_mk.utils.before_app_install"
# after_app_install = "erpnext_scanner_mk.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "erpnext_scanner_mk.utils.before_app_uninstall"
# after_app_uninstall = "erpnext_scanner_mk.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "erpnext_scanner_mk.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "erpnext_scanner_mk.notifications.get_notification_config"

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
# 		"erpnext_scanner_mk.tasks.all"
# 	],
# 	"daily": [
# 		"erpnext_scanner_mk.tasks.daily"
# 	],
# 	"hourly": [
# 		"erpnext_scanner_mk.tasks.hourly"
# 	],
# 	"weekly": [
# 		"erpnext_scanner_mk.tasks.weekly"
# 	],
# 	"monthly": [
# 		"erpnext_scanner_mk.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "erpnext_scanner_mk.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "erpnext_scanner_mk.custom.task.customtaskmixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "erpnext_scanner_mk.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "erpnext_scanner_mk.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["erpnext_scanner_mk.utils.before_request"]
# after_request = ["erpnext_scanner_mk.utils.after_request"]

# Job Events
# ----------
# before_job = ["erpnext_scanner_mk.utils.before_job"]
# after_job = ["erpnext_scanner_mk.utils.after_job"]

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
# 	"erpnext_scanner_mk.auth.validate"
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

# Menu Items
# ----------
# Add menu items to the desk
app_menu = [
	{
		"label": "ERPNext Scanner MK",
		"icon": "file-invoice",
		"items": [
			{
				"label": "Invoice Intake Log",
				"name": "Invoice Intake Log",
				"doctype": "Invoice Intake Log",
				"type": "doctype"
			},
			{
				"label": "Invoice Intake Settings",
				"name": "Invoice Intake Settings",
				"doctype": "Invoice Intake Settings",
				"type": "doctype"
			}
		]
	}
]
