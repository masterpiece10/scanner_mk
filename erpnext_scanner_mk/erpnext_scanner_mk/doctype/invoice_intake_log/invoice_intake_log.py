import frappe
import json
from frappe import _

class InvoiceIntakeLog(Document):
	"""DocType for tracking invoice intake processing."""

	def validate(self):
		self.validate_attachment()

	def validate_attachment(self):
		"""Ensure an invoice attachment is provided."""
		if not self.invoice_attachment:
			frappe.throw("Invoice Attachment is required.")

	def after_insert(self):
		"""Trigger background job right after insert if attachment is present.
		
		Note: Only after_insert is used (not on_update) to avoid duplicate enqueueing.
		on_update would fire on every save during processing, causing race conditions.
		"""
		if self.invoice_attachment and self.status == "Pending" and not self.flags.from_enqueue:
			self._enqueue_processing()

	def _enqueue_processing(self):
		"""Enqueue the background job for invoice processing."""
		frappe.enqueue(
			"erpnext_scanner_mk.erpnext_scanner_mk.erpnext_scanner_mk.doctype.invoice_intake_log.invoice_intake_log.process_intake_log",
			doc_name=self.name,
			queue="long",
			timeout=600,
		)

	def process_now(self):
		"""Manually trigger processing from UI."""
		try:
			process_intake_log(self.name)
			frappe.msgprint(_("Processing started successfully."))
			return True
		except Exception as e:
			frappe.msgprint(_("Failed to start processing: {0}").format(str(e)))
			return False

@frappe.whitelist()
def process_intake_log(doc_name):
	"""Background job: Run AI extraction and then create Purchase Invoice.

	This is the main pipeline function that:
	1. Runs AI extraction on the attached file
	2. Stores the extracted JSON
	3. Creates a Purchase Invoice via fuzzy matching

	Args:
		doc_name: The name of the Invoice Intake Log document.
	"""
	try:
		# Retry up to 5 times to find the document (handles race condition
		# where the background job runs before the DB commit completes)
		intake_log = None
		for attempt in range(5):
			try:
				intake_log = frappe.get_doc("Invoice Intake Log", doc_name)
				break
			except frappe.DoesNotExistError:
				if attempt < 4:
					frappe.db.rollback()
					import time
					time.sleep(1)
				else:
					raise
		if intake_log is None:
			raise frappe.DoesNotExistError(f"Invoice Intake Log {doc_name} not found after retries")

		# Mark as processing
		intake_log.flags.from_enqueue = True
		intake_log.status = "Processing"
		intake_log.save(ignore_permissions=True)
		frappe.db.commit()

		# Step 1: Run AI extraction
		from erpnext_scanner_mk.erpnext_scanner_mk.erpnext_scanner_mk.integrations.ai_client import AIClient

		client = AIClient()
		extracted_data = client.extract_invoice_data(
			intake_log.invoice_attachment, intake_log_name=doc_name
		)

		if extracted_data is None:
			# Error was already logged by AIClient._log_error
			return

		# Step 2: Store the extracted JSON
		# Reload the document to avoid TimestampMismatchError (AIClient modifies it via _log_progress)
		intake_log = frappe.get_doc("Invoice Intake Log", doc_name)
		intake_log.flags.from_enqueue = True
		intake_log.extracted_json = json.dumps(extracted_data, indent=2)
		intake_log.save(ignore_permissions=True)
		frappe.db.commit()

		# Step 3: Create Purchase Invoice via processor
		from erpnext_scanner_mk.erpnext_scanner_mk.erpnext_scanner_mk.utils.processor import InvoiceDataProcessor

		processor = InvoiceDataProcessor(intake_log_name=doc_name)
		pi_name = processor.create_purchase_invoice(doc_name)

		if pi_name:
			frappe.logger(__name__).info(
				_("Successfully processed intake log {0} -> Purchase Invoice {1}").format(
					doc_name, pi_name
				)
			)
		else:
			frappe.logger(__name__).warning(
				_("Processing completed but Purchase Invoice creation returned None for {0}").format(
					doc_name
				)
			)

	except Exception as e:
		frappe.logger(__name__).error(
			_("Error in process_intake_log for {0}: {1}\n{2}").format(
				doc_name, str(e), frappe.get_traceback()
			)
		)
		try:
			# Reload the document to avoid TimestampMismatchError
			intake_log = frappe.get_doc("Invoice Intake Log", doc_name)
			intake_log.flags.from_enqueue = True
			intake_log.status = "Error"
			row = intake_log.append("error_log", {})
			row.timestamp = frappe.utils.now()
			row.status_update = _("Pipeline Error")
			row.details = str(e)
			intake_log.save(ignore_permissions=True)
			frappe.db.commit()
		except Exception:
			pass
