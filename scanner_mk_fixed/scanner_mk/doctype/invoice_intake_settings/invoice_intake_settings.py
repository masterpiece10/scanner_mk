import frappe
from frappe import _

class InvoiceIntakeSettings(Document):
	"""DocType for managing invoice intake settings."""

	def validate(self):
		"""Validate settings before saving."""
		self.validate_api_configuration()

	def validate_api_configuration(self):
		"""Validate API configuration based on provider."""
		if self.api_provider == "DeepSeek VL" and not self.api_key:
			frappe.throw(_("API Key is required for DeepSeek VL provider."))
		
		if self.api_provider == "OpenRouter" and not self.api_key:
			frappe.throw(_("API Key is required for OpenRouter provider."))
		
		if self.api_provider == "Local LLM" and not self.local_llm_endpoint:
			frappe.throw(_("Local LLM Endpoint is required for Local LLM provider."))

	def get_api_key(self):
		"""Get decrypted API key."""
		if self.api_key:
			return frappe.utils.password.get_decrypted_password(
				"Invoice Intake Settings", "Invoice Intake Settings", "api_key"
			)
		return None

def get_settings():
	"""Get Invoice Intake Settings singleton."""
	return frappe.get_single("Invoice Intake Settings")
