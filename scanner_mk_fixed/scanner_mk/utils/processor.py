import frappe
import json
from frappe import _
from rapidfuzz import process, fuzz

class InvoiceDataProcessor:
	"""Processor for mapping extracted invoice data to ERPNext documents."""

	FUZZY_THRESHOLD = 80  # Minimum score for fuzzy matching

	def __init__(self, intake_log_name=None):
		"""Initialize the processor.
		
		Args:
			intake_log_name: Name of the Invoice Intake Log for logging.
		"""
		self.intake_log_name = intake_log_name

	def _log_progress(self, status_update, details):
		"""Log progress to the intake log if available."""
		if self.intake_log_name:
			try:
				intake_log = frappe.get_doc("Invoice Intake Log", self.intake_log_name)
				row = intake_log.append("error_log", {})
				row.timestamp = frappe.utils.now()
				row.status_update = status_update
				row.details = details
				intake_log.save(ignore_permissions=True)
				frappe.db.commit()
			except Exception:
				pass  # Silently fail if we can't log

	def _set_intake_log_error(self, doc_name, error_msg):
		"""Set the intake log to error status."""
		if doc_name:
			try:
				intake_log = frappe.get_doc("Invoice Intake Log", doc_name)
				intake_log.status = "Error"
				row = intake_log.append("error_log", {})
				row.timestamp = frappe.utils.now()
				row.status_update = _("Processor Error")
				row.details = error_msg
				intake_log.save(ignore_permissions=True)
				frappe.db.commit()
			except Exception:
				pass

	def _fuzzy_match_supplier(self, vendor_name):
		"""Fuzzy match a vendor name against existing Suppliers in ERPNext."""
		if not vendor_name:
			return None

		# Get all existing supplier names
		suppliers = frappe.get_all("Supplier", fields=["name"])
		supplier_names = [s.name for s in suppliers]

		if not supplier_names:
			return None

		# Use rapidfuzz to find the best match
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
		"""Fuzzy match an item description against existing Items in ERPNext."""
		if not item_description:
			return None

		# Get all existing item names/descriptions
		items = frappe.get_all("Item", fields=["item_name", "item_code"])
		item_names = [item.item_name or item.item_code for item in items]

		if not item_names:
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
			return None

		self._log_progress(
			_("Resolving Supplier"),
			_("Looking for supplier: {0}").format(vendor_name)
		)

		# Try fuzzy matching first
		matched_supplier = self._fuzzy_match_supplier(vendor_name)
		if matched_supplier:
			self._log_progress(
				_("Supplier Matched"),
				_("Found existing supplier: {0}").format(matched_supplier)
			)
			return matched_supplier

		# Create new supplier if no match found
		try:
			supplier = frappe.get_doc({
				"doctype": "Supplier",
				"supplier_name": vendor_name,
				"supplier_type": "Company"  # Default type
			})
			supplier.insert(ignore_permissions=True)
			frappe.db.commit()

			self._log_progress(
				_("Supplier Created"),
				_("Created new supplier: {0}").format(supplier.name)
			)

			return supplier.name

		except Exception as e:
			frappe.logger(__name__).error(
				_("Failed to create supplier '{0}': {1}").format(vendor_name, str(e))
			)
			return None

	def resolve_item(self, item_description):
		"""Resolve an item description to an Item document.
		
		First tries fuzzy matching against existing items.
		If no match is found, creates a new Item.
		
		Args:
			item_description: The item description extracted from the invoice.
			
		Returns:
			The item_code of the Item document.
		"""
		if not item_description:
			return None

		self._log_progress(
			_("Resolving Item"),
			_("Looking for item: {0}").format(item_description)
		)

		# Try fuzzy matching first
		matched_item = self._fuzzy_match_item(item_description)
		if matched_item:
			self._log_progress(
				_("Item Matched"),
				_("Found existing item: {0}").format(matched_item)
			)
			return matched_item

		# Create new item if no match found
		try:
			# Generate item code from description (clean and truncate)
			item_code = item_description.upper()[:50]
			item_code = ''.join(c for c in item_code if c.isalnum() or c in (' ', '-', '_'))
			item_code = item_code.replace(' ', '_')
			
			# Ensure unique item code
			base_code = item_code
			counter = 1
			while frappe.db.exists("Item", item_code):
				item_code = f"{base_code}_{counter}"
				counter += 1

			item = frappe.get_doc({
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_description,
				"item_group": "All Item Groups",  # Default group
				"stock_uom": "Nos",  # Default UOM
				"is_stock_item": 0,  # Service item by default
				"include_item_in_manufacturing": 0
			})
			item.insert(ignore_permissions=True)
			frappe.db.commit()

			self._log_progress(
				_("Item Created"),
				_("Created new item: {0} ({1})").format(item.item_name, item.item_code)
			)

			return item.item_code

		except Exception as e:
			frappe.logger(__name__).error(
				_("Failed to create item '{0}': {1}").format(item_description, str(e))
			)
			return None

	def create_purchase_invoice(self, doc_name):
		"""Create a Purchase Invoice from extracted invoice data.
		
		Args:
			doc_name: The name of the Invoice Intake Log document.
			
		Returns:
			The name of the created Purchase Invoice, or None if failed.
		"""
		try:
			# Get the intake log document
			intake_log = frappe.get_doc("Invoice Intake Log", doc_name)
			
			if not intake_log.extracted_json:
				error_msg = _("No extracted JSON data found in intake log.")
				self._log_progress(_("Missing Data"), error_msg)
				self._set_intake_log_error(doc_name, error_msg)
				return None

			# Parse extracted JSON
			try:
				extracted_data = json.loads(intake_log.extracted_json)
			except json.JSONDecodeError as e:
				error_msg = _("Invalid JSON in extracted data: {0}").format(str(e))
				self._log_progress(_("JSON Parse Error"), error_msg)
				self._set_intake_log_error(doc_name, error_msg)
				return None

			self._log_progress(
				_("Creating Purchase Invoice"),
				_("Starting Purchase Invoice creation from extracted data.")
			)

			# Resolve supplier
			supplier = self.resolve_supplier(extracted_data.get("vendor_name"))
			if not supplier:
				error_msg = _("Could not resolve supplier: {0}").format(extracted_data.get("vendor_name"))
				self._log_progress(_("Supplier Error"), error_msg)
				self._set_intake_log_error(doc_name, error_msg)
				return None

			# Create Purchase Invoice
			pi_doc = frappe.get_doc({
				"doctype": "Purchase Invoice",
				"supplier": supplier,
				"posting_date": extracted_data.get("date") or frappe.utils.today(),
				"due_date": frappe.utils.add_months(frappe.utils.today(), 1),
				"currency": extracted_data.get("currency") or frappe.db.get_value("Company", frappe.defaults.get_user_default("Company"), "default_currency"),
				"conversion_rate": 1.0,
				"status": "Draft",
				"bill_no": extracted_data.get("invoice_number"),
				"bill_date": extracted_data.get("date"),
			})

			# Add items
			items = extracted_data.get("items", [])
			if not items:
				error_msg = _("No items found in extracted data.")
				self._log_progress(_("No Items"), error_msg)
				self._set_intake_log_error(doc_name, error_msg)
				return None

			for item_data in items:
				item_code = self.resolve_item(item_data.get("description"))
				if not item_code:
					self._log_progress(
						_("Item Skipped"),
						_("Could not resolve item: {0}").format(item_data.get("description"))
					)
					continue

				# Add item to Purchase Invoice
				pi_doc.append("items", {
					"item_code": item_code,
					"qty": item_data.get("qty", 1),
					"rate": item_data.get("rate", 0),
					"expense_account": "Cost of Goods Sold - SC",  # Default account
					"cost_center": "Main - SC",  # Default cost center
				})

			if not pi_doc.items:
				error_msg = _("No valid items could be added to Purchase Invoice.")
				self._log_progress(_("No Valid Items"), error_msg)
				self._set_intake_log_error(doc_name, error_msg)
				return None

			# Insert and submit
			pi_doc.insert(ignore_permissions=True)
			frappe.db.commit()

			# Update intake log with link
			intake_log.purchase_invoice = pi_doc.name
			intake_log.status = "Processed"
			intake_log.save(ignore_permissions=True)
			frappe.db.commit()

			self._log_progress(
				_("Processing Complete"),
				_("Successfully linked Purchase Invoice '{0}' to intake log.").format(pi_doc.name)
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

		except Exception as e:
			error_msg = _("Unexpected error creating Purchase Invoice: {0}").format(str(e))
			self._log_progress(_("Unexpected Error"), error_msg)
			self._set_intake_log_error(doc_name, error_msg)
			frappe.logger(__name__).error(
				_("Error in InvoiceDataProcessor.create_purchase_invoice: {0}\n{1}").format(
					str(e), frappe.get_traceback()
				)
			)
			return None
