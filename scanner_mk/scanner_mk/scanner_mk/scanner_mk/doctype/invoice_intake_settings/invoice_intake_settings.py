import frappe
from frappe.model.document import Document


class InvoiceIntakeSettings(Document):
	"""Settings for Invoice Intake processing via AI APIs."""

	def validate(self):
		self.validate_api_configuration()

	def validate_api_configuration(self):
		"""Validate API configuration settings."""
		if self.api_provider == "OpenRouter" and not self.openrouter_model:
			frappe.throw("OpenRouter Model is required when using OpenRouter as the API provider.")
		if self.api_provider == "Local LLM" and not self.local_llm_endpoint:
			frappe.throw("Local LLM Endpoint URL is required when using a Local LLM.")
		if self.api_provider == "Local LLM" and not self.local_llm_model:
			frappe.throw("Local LLM Model is required when using a Local LLM.")

	@staticmethod
	def get_settings():
		"""Get Invoice Intake Settings with caching."""
		cache_key = "invoice_intake_settings"
		cached = frappe.cache().get_value(cache_key)
		if cached:
			return cached

		settings = frappe.get_single("Invoice Intake Settings")
		settings_dict = settings.as_dict()

		# Cache for 1 hour
		frappe.cache().set_value(cache_key, settings_dict, expires_in_sec=3600)
		return settings_dict

	@staticmethod
	def get_api_key():
		"""Get the decrypted API key."""
		settings = frappe.get_single("Invoice Intake Settings")
		if settings.api_key:
			return frappe.utils.password.get_decrypted_password(
				"Invoice Intake Settings", "Invoice Intake Settings", "api_key"
			)
		return None

	def on_update(self):
		"""Clear cache when settings are updated."""
		frappe.cache().delete_value("invoice_intake_settings")
