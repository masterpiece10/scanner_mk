import frappe
import json
from frappe import _
from frappe.utils import cint, flt, nowdate
from rapidfuzz import fuzz, process


class InvoiceDataProcessor:
	"""Handles data mapping from AI-extracted invoice data to ERPNext documents."""

	DEFAULT_ITEM_GROUP = "All Item Groups"
	FUZZY_THRESHOLD = 80  # 80% confidence threshold for fuzzy matching

	def __init__(self, intake_log_name=None):
		"""Initialize the processor.

		Args:
			intake_log_name: Optional name of the Invoice Intake Log document for logging.
		"""
		self.intake_log_name = intake_log_name
		self.settings = frappe.get_single("Invoice Intake Settings")

	def _log_progress(self, status_update, details=None):
		"""Log a progress entry to the Intake Processing Log child table.

		Args:
			status_update: A short status update string.
			details: Optional detailed description.
		"""
		if not self.intake_log_name:
			return

		try:
			intake_log = frappe.get_doc("Invoice Intake Log", self.intake_log_name)
			row = intake_log.append("error_log", {})
			row.timestamp = frappe.utils.now()
			row.status_update = status_update
			if details:
				row.details = details
			intake_log.save(ignore_permissions=True)
			frappe.db.commit()
		except Exception as e:
			frappe.log_error(
				_("Failed to log progress to intake log {0}: {1}").format(
					self.intake_log_name, str(e)
				),
				"Invoice Data Processor",
			)

	def _fuzzy_match_supplier(self, vendor_name):
		"""Fuzzy match a vendor name against existing Suppliers in ERPNext.

		Uses rapidfuzz for fuzzy string matching against all supplier names.

		Args:
			vendor_name: The vendor name extracted from the invoice.

		Returns:
			The name of the matched Supplier document, or None if no match found.
		"""
		if not vendor_name:
			return None

		vendor_name = vendor_name.strip()

		# Get all supplier names
		suppliers = frappe.get_all("Supplier", pluck="name")

		if not suppliers:
			return None

		# Use rapidfuzz to find the best match
		# Use token_set_ratio which handles cases where vendor name has extra tokens
		# (e.g., "Newly Weds Foods (Thailand) Limited" should match "Newly Weds Foods")
		best_match = process.extractOne(
			vendor_name,
			suppliers,
			scorer=fuzz.token_set_ratio,
			score_cutoff=self.FUZZY_THRESHOLD,
		)

		if best_match:
			matched_name, score, idx = best_match
			frappe.logger(__name__).debug(
				_("Fuzzy matched supplier '{0}' to '{1}' with score {2}").format(
					vendor_name, matched_name, score
				)
			)
			return matched_name

		return None

	def _fuzzy_match_item(self, item_description):
		"""Fuzzy match an item description against existing Items in ERPNext.

		Args:
			item_description: The item description extracted from the invoice.

		Returns:
			The name of the matched Item document, or None if no match found.
		"""
		if not item_description:
			return None

		item_description = item_description.strip()

		# Get all item names
		items = frappe.get_all("Item", pluck="name")

		if not items:
			return None

		# Use rapidfuzz to find the best match
		best_match = process.extractOne(
			item_description,
			items,
			scorer=fuzz.token_sort_ratio,
			score_cutoff=self.FUZZY_THRESHOLD,
		)

		if best_match:
			matched_name, score, idx = best_match
			frappe.logger(__name__).debug(
				_("Fuzzy matched item '{0}' to '{1}' with score {2}").format(
					item_description, matched_name, score
				)
			)
			return matched_name

		return None

	def resolve_supplier(self, vendor_name):
		"""Resolve a vendor name to a Supplier document.

		First tries fuzzy matching against existing suppliers.
		If no match is found, creates a new Supplier.

		Args:
			vendor_name: The vendor name extracted from the invoice.

		Returns:
			The name of the Supplier document.
		"""
		if not vendor_name:
			frappe.throw(_("Vendor name is required to resolve a supplier."))

		vendor_name = vendor_name.strip()

		# Step 1: Try fuzzy matching
		matched_supplier = self._fuzzy_match_supplier(vendor_name)
		if matched_supplier:
			self._log_progress(
				_("Supplier Matched"),
				_("Fuzzy matched vendor '{0}' to existing supplier '{1}'").format(
					vendor_name, matched_supplier
				),
			)
			return matched_supplier

		# Step 2: No match found - create a new Supplier
		self._log_progress(
			_("Creating New Supplier"),
			_("No existing supplier found for '{0}'. Creating a new supplier.").format(
				vendor_name
			),
		)

		try:
			supplier = frappe.get_doc({
				"doctype": "Supplier",
				"supplier_name": vendor_name,
				"supplier_group": _("Services"),
				"supplier_type": _("Company"),
			})
			supplier.insert(ignore_permissions=True)
			frappe.db.commit()

			self._log_progress(
				_("Supplier Created"),
				_("Created new supplier '{0}'").format(supplier.name),
			)

			return supplier.name

		except Exception as e:
			# If supplier creation failed due to duplicate entry, try to find the existing one
			if "Duplicate entry" in str(e):
				existing = frappe.db.get_value("Supplier", {"supplier_name": vendor_name}, "name")
				if existing:
					self._log_progress(
						_("Supplier Found"),
						_("Supplier '{0}' already exists. Using existing supplier '{1}'.").format(
							vendor_name, existing
						),
					)
					return existing

			error_msg = _("Failed to create supplier '{0}': {1}").format(vendor_name, str(e))
			frappe.log_error(error_msg, "Invoice Data Processor")
			self._log_progress(_("Supplier Creation Failed"), error_msg)
			raise

	def resolve_item(self, item_description, default_item_group=None):
		"""Resolve an item description to an Item document.

		First tries fuzzy matching against existing items.
		If no match is found above 80% confidence, creates a new Item.

		Args:
			item_description: The item description extracted from the invoice.
			default_item_group: Optional item group for new items. Falls back to DEFAULT_ITEM_GROUP.

		Returns:
			The name of the Item document.
		"""
		if not item_description:
			frappe.throw(_("Item description is required to resolve an item."))

		item_description = item_description.strip()

		# Step 1: Try fuzzy matching
		matched_item = self._fuzzy_match_item(item_description)
		if matched_item:
			self._log_progress(
				_("Item Matched"),
				_("Fuzzy matched item '{0}' to existing item '{1}'").format(
					item_description, matched_item
				),
			)
			return matched_item

		# Step 2: No match found - create a new Item
		item_group = default_item_group or self.DEFAULT_ITEM_GROUP

		self._log_progress(
			_("Creating New Item"),
			_("No existing item found for '{0}'. Creating a new item in group '{1}'.").format(
				item_description, item_group
			),
		)

		try:
			# Generate a clean item code from the description
			item_code = self._generate_item_code(item_description)

			item = frappe.get_doc({
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_description,
				"description": item_description,
				"item_group": item_group,
				"is_stock_item": 0,
				"is_purchase_item": 1,
				"is_sales_item": 0,
				"stock_uom": _("Nos"),
			})
			item.insert(ignore_permissions=True)
			frappe.db.commit()

			self._log_progress(
				_("Item Created"),
				_("Created new item '{0}' with code '{1}'").format(
					item_description, item.name
				),
			)

			return item.name

		except Exception as e:
			error_msg = _("Failed to create item '{0}': {1}").format(item_description, str(e))
			frappe.log_error(error_msg, "Invoice Data Processor")
			self._log_progress(_("Item Creation Failed"), error_msg)
			raise

	def _generate_item_code(self, description):
		"""Generate a clean item code from a description string.

		Args:
			description: The item description.

		Returns:
			A sanitized item code string.
		"""
		# Take first 40 chars, replace spaces with hyphens, remove special chars
		code = description[:40].strip()
		code = "".join(c if c.isalnum() or c in " -_" else "" for c in code)
		code = code.replace(" ", "-").replace("--", "-").strip("-")
		code = code.upper()

		if not code:
			code = "NEW-ITEM"

		# Ensure uniqueness by appending a number if needed
		existing = frappe.db.exists("Item", code)
		if existing:
			counter = 1
			while frappe.db.exists("Item", f"{code}-{counter}"):
				counter += 1
			code = f"{code}-{counter}"

		return code

	def create_purchase_invoice(self, doc_name):
		"""Create a Draft Purchase Invoice from the extracted JSON stored in an Invoice Intake Log.

		This is the main entry point for processing. It:
		1. Reads the Invoice Intake Log document
		2. Parses the extracted JSON
		3. Resolves the supplier via fuzzy matching (or creates one)
		4. Resolves each item via fuzzy matching (or creates items)
		5. Creates a Draft Purchase Invoice in ERPNext
		6. Links the Purchase Invoice back to the Invoice Intake Log

		Args:
			doc_name: The name of the Invoice Intake Log document to process.

		Returns:
			The name of the created Purchase Invoice, or None if processing fails.
		"""
		try:
			# Step 1: Get the intake log document
			intake_log = frappe.get_doc("Invoice Intake Log", doc_name)

			self._log_progress(
				_("Processing Started"),
				_("Starting Purchase Invoice creation from intake log '{0}'").format(doc_name),
			)

			# Step 2: Parse the extracted JSON
			if not intake_log.extracted_json:
				frappe.throw(_("No extracted JSON found in Invoice Intake Log '{0}'").format(doc_name))

			extracted_data = json.loads(intake_log.extracted_json)

			# Step 3: Resolve the supplier
			vendor_name = extracted_data.get("vendor_name")
			if not vendor_name:
				# Fall back to default supplier from settings
				if self.settings.default_supplier:
					supplier = self.settings.default_supplier
					self._log_progress(
						_("Using Default Supplier"),
						_("No vendor name in extracted data. Using default supplier '{0}'").format(
							supplier
						),
					)
				else:
					frappe.throw(_("Vendor name is missing from extracted data and no default supplier is configured."))
			else:
				supplier = self.resolve_supplier(vendor_name)

			# Step 4: Update status to Processing
			# Reload to avoid TimestampMismatchError (_log_progress may have modified the document)
			intake_log = frappe.get_doc("Invoice Intake Log", doc_name)
			intake_log.status = "Processing"
			intake_log.save(ignore_permissions=True)
			frappe.db.commit()

			# Step 5: Resolve items and build the items table
			purchase_invoice_items = []
			items_data = extracted_data.get("items", [])

			if not items_data:
				self._log_progress(
					_("No Items Found"),
					_("No line items found in extracted data. Creating invoice without items."),
				)

			for idx, item_data in enumerate(items_data):
				description = item_data.get("description", "")
				qty = flt(item_data.get("qty", 1))
				rate = flt(item_data.get("rate", 0))

				if not description:
					self._log_progress(
						_("Skipping Item"),
						_("Item at index {0} has no description. Skipping.").format(idx),
					)
					continue

				# Resolve the item (fuzzy match or create)
				item_name = self.resolve_item(description)

				# Round quantity to nearest integer for UOM "Nos" (default) to avoid fraction errors
				# ERPNext UOM "Nos" has "Must be Whole Number" enabled by default
				# Most invoices won't have decimal quantities, so rounding is safe
				qty = round(qty) if qty > 0 else 1

				purchase_invoice_items.append({
					"item_code": item_name,
					"qty": qty,
					"rate": rate,
					"description": description,
				})

			# Step 6: Get totals and currency from extracted data
			totals = extracted_data.get("totals", {})
			invoice_date = extracted_data.get("date", nowdate())
			invoice_number = extracted_data.get("invoice_number", "")
			currency = extracted_data.get("currency")

			# Step 7: Create the Purchase Invoice
			self._log_progress(
				_("Creating Purchase Invoice"),
				_("Creating draft Purchase Invoice for supplier '{0}' with {1} items.").format(
					supplier, len(purchase_invoice_items)
				),
			)

			# Determine currency and credit_to account
			company = frappe.defaults.get_user_default("company") or frappe.db.get_single_value("Global Defaults", "default_company")
			company_doc = frappe.get_doc("Company", company) if company else None

			if currency:
				# Use the currency from extracted data
				pi_currency = currency
				# Find the appropriate payable account for this currency
				credit_to = frappe.db.get_value(
					"Account",
					{"company": company, "account_currency": currency, "account_type": "Payable", "is_group": 0},
					"name"
				)
				if not credit_to:
					# Fall back to company default payable account
					credit_to = company_doc.default_payable_account if company_doc else None
			else:
				# Use company default currency
				pi_currency = company_doc.default_currency if company_doc else "HKD"
				credit_to = company_doc.default_payable_account if company_doc else None

			pi_doc = frappe.get_doc({
				"doctype": "Purchase Invoice",
				"supplier": supplier,
				"posting_date": invoice_date,
				"bill_no": invoice_number,
				"bill_date": invoice_date,
				"items": purchase_invoice_items,
				"currency": pi_currency,
				"credit_to": credit_to,
				"is_paid": 0,
				"docstatus": 0,  # Draft
			})

			# Set totals if provided (they will be overridden by items but we set as reference)
			if totals:
				if "grand_total" in totals and totals["grand_total"] is not None:
					pi_doc.base_grand_total = flt(totals["grand_total"])

			pi_doc.insert(ignore_permissions=True)
			frappe.db.commit()

			self._log_progress(
				_("Purchase Invoice Created"),
				_("Created draft Purchase Invoice '{0}' for supplier '{1}'").format(
					pi_doc.name, supplier
				),
			)

			# Step 8: Link the Purchase Invoice back to the Intake Log
			# Reload to avoid TimestampMismatchError (_log_progress may have modified the document)
			intake_log = frappe.get_doc("Invoice Intake Log", doc_name)
			intake_log.purchase_invoice = pi_doc.name
			intake_log.status = "Processed"
			intake_log.save(ignore_permissions=True)
			frappe.db.commit()

			self._log_progress(
				_("Processing Complete"),
				_("Successfully linked Purchase Invoice '{0}' to intake log.").format(pi_doc.name),
			)

			frappe.logger(__name__).info(
				_("Successfully created Purchase Invoice {0} from intake log {1}").format(
					pi_doc.name, doc_name
				)
			)

			return pi_doc.name

		except json.JSONDecodeError as e:
			error_msg = _("Invalid JSON in extracted data: {0}").format(str(e))
			self._log_progress(_("JSON Parse Error"), error_msg)
			self._set_intake_log_error(doc_name, error_msg)
			return None

		except frappe.ValidationError:
			# Re-raise validation errors so they propagate to the caller
			raise

		except Exception as e:
			error_msg = _("Failed to create Purchase Invoice: {0}").format(str(e))
			frappe.log_error(
				_("Error in create_purchase_invoice for {0}: {1}\n{2}").format(
					doc_name, str(e), frappe.get_traceback()
				),
				"Invoice Data Processor",
			)
			self._log_progress(_("Processing Failed"), error_msg)
			self._set_intake_log_error(doc_name, error_msg)
			return None

	def _set_intake_log_error(self, doc_name, error_msg):
		"""Set the intake log status to Error with the given message.

		Args:
			doc_name: The name of the Invoice Intake Log document.
			error_msg: The error message to log.
		"""
		try:
			intake_log = frappe.get_doc("Invoice Intake Log", doc_name)
			intake_log.status = "Error"
			row = intake_log.append("error_log", {})
			row.timestamp = frappe.utils.now()
			row.status_update = _("Processing Failed")
			row.details = error_msg
			intake_log.save(ignore_permissions=True)
			frappe.db.commit()
		except Exception as e:
			frappe.log_error(
				_("Failed to set error status on intake log {0}: {1}").format(doc_name, str(e)),
				"Invoice Data Processor",
			)
