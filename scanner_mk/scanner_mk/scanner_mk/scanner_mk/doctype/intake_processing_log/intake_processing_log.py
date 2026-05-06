import frappe
from frappe.model.document import Document


class IntakeProcessingLog(Document):
	"""Child DocType to store timestamped status updates for Invoice Intake processing."""

	def before_save(self):
		"""Set timestamp before saving if not already set."""
		if not self.timestamp:
			self.timestamp = frappe.utils.now()
