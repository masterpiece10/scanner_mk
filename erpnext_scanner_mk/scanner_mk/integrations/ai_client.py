import frappe
import json
import base64
import requests
from frappe import _
from frappe.utils.password import get_decrypted_password

class AIClient:
	"""Client for communicating with DeepSeek/OpenRouter/Local LLM APIs to extract invoice data."""

	DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
	OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

	def __init__(self):
		"""Initialize the AI client by reading configuration from Invoice Intake Settings."""
		self.settings = frappe.get_single("Invoice Intake Settings")
		self.api_provider = self.settings.api_provider
		self.api_key = self._get_decrypted_api_key()
		self.openrouter_model = self.settings.openrouter_model
		self.local_llm_endpoint = self.settings.local_llm_endpoint
		self.local_llm_model = self.settings.local_llm_model

	def _get_decrypted_api_key(self):
		"""Get the decrypted API key from settings."""
		if self.settings.api_key:
			return get_decrypted_password(
				"Invoice Intake Settings", "Invoice Intake Settings", "api_key"
			)
		return None

	def _is_debug_logging_enabled(self):
		"""Check if debug logging is enabled in settings."""
		try:
			return bool(self.settings.get("debug_logging", 0))
		except Exception:
			return False

	def _log_debug(self, message, method="Invoice Intake AI Client"):
		"""Log a debug message to the Error Log only if debug logging is enabled."""
		if self._is_debug_logging_enabled():
			frappe.logger(__name__).debug(message)

	def _log_error_always(self, message, method="Invoice Intake AI Client"):
		"""Log an error message to the Error Log ALWAYS (regardless of debug setting)."""
		frappe.log_error(message, method)

	def _log_progress(self, intake_log_name, status_update, details):
		"""Log a progress entry to the Intake Processing Log child table."""
		if not intake_log_name:
			self._log_debug(
				_("Progress log skipped (no intake log name): {0} - {1}").format(status_update, details),
				"Invoice Intake AI Client",
			)
			return

		try:
			intake_log = frappe.get_doc("Invoice Intake Log", intake_log_name)
			row = intake_log.append("error_log", {})
			row.timestamp = frappe.utils.now()
			row.status_update = status_update
			row.details = details
			intake_log.save(ignore_permissions=True)
			frappe.db.commit()

			self._log_debug(
				_("Progress logged to {0}: {1} - {2}").format(intake_log_name, status_update, details),
				"Invoice Intake AI Client",
			)
		except Exception as e:
			self._log_debug(
				_("Failed to log progress to intake log {0}: {1}").format(
					intake_log_name, str(e)
				),
				"Invoice Intake AI Client",
			)

	def extract_invoice_data(self, file_url, intake_log_name=None):
		"""Extract invoice data from a file using AI vision or OCR fallback.

		Args:
			file_url: The URL or path of the file attached to the document.
			intake_log_name: The name of the Invoice Intake Log document for logging.

		Returns:
			Extracted data dict, or None if extraction fails completely.
		"""
		try:
			self._log_progress(
				intake_log_name,
				"Pipeline Started",
				_("Starting AI extraction pipeline for file: {0}").format(file_url),
			)

			# --- Attempt 1: Vision-based extraction ---
			self._log_progress(
				intake_log_name,
				"Vision Extraction",
				_("Attempt 1/2: Vision-based AI extraction..."),
			)

			extracted_data = self._extract_with_vision(file_url, intake_log_name)

			if extracted_data:
				self._log_progress(
					intake_log_name,
					"Pipeline Complete",
					_("Successfully extracted invoice data via vision AI."),
				)
				return extracted_data

			# --- Attempt 2: OCR + AI fallback ---
			self._log_progress(
				intake_log_name,
				"OCR Fallback",
				_("Attempt 2/2: Vision failed. Running local OCR + AI structuring..."),
			)

			extracted_data = self._extract_with_ocr_fallback(file_url, intake_log_name)

			if extracted_data:
				self._log_progress(
					intake_log_name,
					"Pipeline Complete",
					_("Successfully extracted invoice data via OCR + AI."),
				)
				return extracted_data

			# --- All attempts failed: Set to Manual Review Needed ---
			reason = _(
				"Both vision-based AI extraction and OCR+AI fallback failed for this invoice. "
				"Please review the attached document and enter the data manually."
			)
			self._set_manual_review(intake_log_name, reason)

			self._log_progress(
				intake_log_name,
				"Pipeline Failed",
				_("All extraction methods failed. Set to Manual Review Needed."),
			)

			return None

		except frappe.ValidationError:
			# Re-raise validation errors (like missing config) so they propagate
			raise

		except Exception as e:
			error_msg = _("Unexpected error during extraction pipeline: {0}").format(str(e))
			self._log_progress(
				intake_log_name,
				"Pipeline Error",
				error_msg,
			)
			self._log_error_always(
				_("Unexpected error in extraction pipeline for {0}: {1}\n{2}").format(
					file_url, str(e), frappe.get_traceback()
				),
				"Invoice Intake AI Client",
			)
			self._set_manual_review(intake_log_name, error_msg)
			return None

	def _set_manual_review(self, intake_log_name, reason):
		"""Set the intake log status to Manual Review Needed and create a ToDo."""
		if not intake_log_name:
			return

		try:
			intake_log = frappe.get_doc("Invoice Intake Log", intake_log_name)
			intake_log.status = "Manual Review Needed"
			intake_log.save(ignore_permissions=True)
			frappe.db.commit()

			# Create a ToDo for manual review
			todo = frappe.get_doc({
				"doctype": "ToDo",
				"description": _("Manual Review Required: {0}").format(reason),
				"reference_type": "Invoice Intake Log",
				"reference_name": intake_log_name,
				"status": "Open",
				"priority": "High",
			})
			todo.insert(ignore_permissions=True)
			frappe.db.commit()

		except Exception as e:
			self._log_debug(
				_("Failed to set manual review status for {0}: {1}").format(
					intake_log_name, str(e)
				),
				"Invoice Intake AI Client",
			)

	def _extract_with_vision(self, file_url, intake_log_name):
		"""Extract invoice data using vision-based AI."""
		try:
			# Get file as base64
			base64_data, mime_type = self._get_file_as_base64(file_url)
			
			# Build prompt for vision extraction
			prompt = self._build_prompt(for_text=False)
			
			# Prepare messages for vision API
			messages = [
				{"role": "system", "content": prompt},
				{
					"role": "user",
					"content": [
						{
							"type": "text",
							"text": "Extract invoice data from this image and return it as JSON."
						},
						{
							"type": "image_url",
							"image_url": {
								"url": f"data:{mime_type};base64,{base64_data}"
							}
						}
					]
				}
			]

			# Call API based on provider
			response = self._call_api(messages)
			
			if response and "choices" in response:
				content = response["choices"][0]["message"]["content"]
				return self._parse_ai_response(content)
			
			return None

		except Exception as e:
			self._log_debug(
				_("Vision extraction failed for {0}: {1}").format(file_url, str(e)),
				"Invoice Intake AI Client",
			)
			return None

	def _extract_with_ocr_fallback(self, file_url, intake_log_name):
		"""Extract invoice data using OCR + AI text processing."""
		try:
			# Step 1: Run local OCR
			from scanner_mk.utils.ocr import OCREngine

			ocr = OCREngine()
			ocr_text = ocr.extract_text(file_url)

			if not ocr_text:
				self._log_progress(
					intake_log_name,
					"OCR Failed",
					_("OCR returned no text for {0}").format(file_url),
				)
				return None

			# Step 2: Send OCR text to AI for structuring
			prompt = self._build_prompt(for_text=True)
			
			messages = [
				{"role": "system", "content": prompt},
				{
					"role": "user",
					"content": ocr_text
				}
			]

			response = self._call_api(messages)
			
			if response and "choices" in response:
				content = response["choices"][0]["message"]["content"]
				return self._parse_ai_response(content)
			
			return None

		except Exception as e:
			self._log_debug(
				_("OCR fallback extraction failed for {0}: {1}").format(file_url, str(e)),
				"Invoice Intake AI Client",
			)
			return None

	def _call_api(self, messages):
		"""Call the appropriate API based on provider."""
		if self.api_provider == "DeepSeek VL":
			return self._call_deepseek_api(messages)
		elif self.api_provider == "OpenRouter":
			return self._call_openrouter_api(messages)
		elif self.api_provider == "Local LLM":
			return self._call_local_llm_api(messages)
		else:
			frappe.throw(_("Unsupported API provider: {0}").format(self.api_provider))

	def _call_deepseek_api(self, messages):
		"""Call DeepSeek VL API."""
		if not self.api_key:
			frappe.throw(_("DeepSeek API key is not configured."))

		headers = {
			"Authorization": f"Bearer {self.api_key}",
			"Content-Type": "application/json"
		}

		payload = {
			"model": "deepseek-vl",
			"messages": messages,
			"max_tokens": 4000,
			"temperature": 0.1
		}

		response = requests.post(
			self.DEEPSEEK_API_URL,
			headers=headers,
			json=payload,
			timeout=120,
		)

		if response.status_code != 200:
			error_msg = _("DeepSeek API error (HTTP {0}): {1}").format(
				response.status_code, response.text[:500]
			)
			frappe.logger(__name__).error(error_msg)
			frappe.throw(error_msg)

		return response.json()

	def _call_openrouter_api(self, messages):
		"""Call OpenRouter API."""
		if not self.api_key:
			frappe.throw(_("OpenRouter API key is not configured."))

		headers = {
			"Authorization": f"Bearer {self.api_key}",
			"Content-Type": "application/json",
			"HTTP-Referer": "https://erpnext.com",
			"X-Title": "ERPNext Scanner MK"
		}

		payload = {
			"model": self.openrouter_model,
			"messages": messages,
			"max_tokens": 4000,
			"temperature": 0.1
		}

		response = requests.post(
			self.OPENROUTER_API_URL,
			headers=headers,
			json=payload,
			timeout=120,
		)

		if response.status_code != 200:
			error_msg = _("OpenRouter API error (HTTP {0}): {1}").format(
				response.status_code, response.text[:500]
			)
			frappe.logger(__name__).error(error_msg)
			frappe.throw(error_msg)

		return response.json()

	def _call_local_llm_api(self, messages):
		"""Call Local LLM API."""
		if not self.local_llm_endpoint:
			frappe.throw(_("Local LLM endpoint is not configured."))

		headers = {
			"Content-Type": "application/json"
		}

		payload = {
			"model": self.local_llm_model,
			"messages": messages,
			"max_tokens": 4000,
			"temperature": 0.1
		}

		response = requests.post(
			self.local_llm_endpoint,
			headers=headers,
			json=payload,
			timeout=300,  # 5 min timeout for local models which can be slower
		)

		if response.status_code != 200:
			error_msg = _("Local LLM API error (HTTP {0}): {1}").format(
				response.status_code, response.text[:500]
			)
			frappe.logger(__name__).error(error_msg)
			frappe.throw(error_msg)

		return response.json()

	def _parse_ai_response(self, content):
		"""Parse AI response content and extract JSON."""
		try:
			# Remove markdown code blocks if present
			content = content.strip()
			if content.startswith("```json"):
				content = content[7:]
			if content.startswith("```"):
				content = content[3:]
			if content.endswith("```"):
				content = content[:-3]
			content = content.strip()

			# Parse JSON
			data = json.loads(content)
			
			# Validate structure
			self._validate_extracted_data(data)
			
			return data

		except json.JSONDecodeError as e:
			frappe.logger(__name__).error(
				_("Failed to parse AI response as JSON: {0}\nContent: {1}").format(
					str(e), content[:500]
				)
			)
			return None
		except ValueError as e:
			frappe.logger(__name__).error(
				_("Invalid extracted data structure: {0}").format(str(e))
			)
			return None

	def _validate_extracted_data(self, data):
		"""Validate that the extracted data has the expected structure."""
		if not isinstance(data, dict):
			raise ValueError(_("Extracted data is not a dictionary."))

		# Check for required top-level keys (at least one should be present)
		expected_keys = {"vendor_name", "date", "invoice_number", "items", "totals"}
		if not any(key in data for key in expected_keys):
			raise ValueError(
				_("Extracted data missing expected invoice fields. Got keys: {0}").format(
					", ".join(data.keys())
				)
			)

		# Validate items structure if present
		if "items" in data and data["items"] is not None:
			if not isinstance(data["items"], list):
				raise ValueError(_("'items' field must be a list."))
			for i, item in enumerate(data["items"]):
				if not isinstance(item, dict):
					raise ValueError(_("Item at index {0} is not a dictionary.").format(i))

		# Validate totals structure if present
		if "totals" in data and data["totals"] is not None:
			if not isinstance(data["totals"], dict):
				raise ValueError(_("'totals' field must be a dictionary."))

	def _build_prompt(self, for_text=False):
		"""Construct the prompt asking the AI to extract invoice data in strict JSON format."""
		# Check if user wants to keep original language
		keep_original = False
		try:
			settings = frappe.get_single("Invoice Intake Settings")
			keep_original = bool(settings.get("keep_original_language", 0))
		except Exception:
			pass

		if keep_original:
			translation_instruction = (
				"Keep vendor names and item descriptions in their ORIGINAL language. "
				"Do NOT translate them to English."
			)
			vendor_desc = "string (the name of the vendor/supplier in its original language, do NOT translate)"
			item_desc = "string (item description in its original language, do NOT translate)"
		else:
			translation_instruction = (
				"Translate vendor names and item descriptions to English where possible."
			)
			vendor_desc = "string (the name of the vendor/supplier, translated to English if non-English)"
			item_desc = "string (item description, translated to English if non-English)"

		system_prompt = (
			"You are an expert multilingual invoice data extraction assistant. "
			"Your task is to extract structured data from invoice images/documents "
			"in ANY language (English, Chinese, Thai, Korean, Japanese, Vietnamese, etc.). "
			f"{translation_instruction} "
			"Always respond with valid JSON only, no markdown formatting, no code blocks."
		)

		if for_text:
			user_prompt = (
				"Below is the OCR-extracted text from an invoice document. "
				"The invoice may be in any language (English, Chinese, Thai, Korean, Japanese, etc.). "
				"Parse this text and extract the structured invoice data from it. "
				f"{translation_instruction} "
				"Return ONLY a valid JSON object with no markdown formatting or code blocks.\n\n"
				"Required JSON schema:\n"
				"{"
				f'\n  "vendor_name": "{vendor_desc}",\n'
				'  "date": "string (invoice date in YYYY-MM-DD format)",\n'
				'  "invoice_number": "string (the invoice number)",\n'
				'  "currency": "string (the currency code e.g. USD, HKD, EUR, CNY, THB, KRW, JPY - use ISO 4217 3-letter code)",\n'
				'  "items": [\n'
				"    {\n"
				f'      "description": "{item_desc}",\n'
				'      "qty": number (quantity as a number),\n'
				'      "rate": number (unit rate/price as a number)\n'
				"    }\n"
				"  ],\n"
				'  "totals": {\n'
				'    "subtotal": number (subtotal before tax),\n'
				'    "tax": number (total tax amount),\n'
				'    "grand_total": number (total including tax)\n'
				"  }\n"
				"}\n\n"
				"If any field is not found in the text, use null for that field. "
				"For items, extract all line items mentioned. "
				"If no items are found, return an empty array for items."
			)
		else:
			user_prompt = (
				"Extract the following information from this invoice image and return it as a strict JSON object. "
				"The invoice may be in any language (English, Chinese, Thai, Korean, Japanese, etc.). "
				f"{translation_instruction} "
				"Do NOT include any markdown formatting, code blocks, or extra text. Return ONLY the raw JSON object.\n\n"
				"Required JSON schema:\n"
				"{"
				f'\n  "vendor_name": "{vendor_desc}",\n'
				'  "date": "string (invoice date in YYYY-MM-DD format)",\n'
				'  "invoice_number": "string (the invoice number)",\n'
				'  "currency": "string (the currency code e.g. USD, HKD, EUR, CNY, THB, KRW, JPY - use ISO 4217 3-letter code)",\n'
				'  "items": [\n'
				"    {\n"
				f'      "description": "{item_desc}",\n'
				'      "qty": number (quantity as a number),\n'
				'      "rate": number (unit rate/price as a number)\n'
				"    }\n"
				"  ],\n"
				'  "totals": {\n'
				'    "subtotal": number (subtotal before tax),\n'
				'    "tax": number (total tax amount),\n'
				'    "grand_total": number (total including tax)\n'
				"  }\n"
				"}\n\n"
				"If any field is not found in the image, use null for that field. "
				"For items, extract all line items mentioned. "
				"If no items are found, return an empty array for items."
			)

		return system_prompt + "\n\n" + user_prompt

	def _get_file_as_base64(self, file_url):
		"""Convert an attached file to base64 encoded string."""
		if not file_url:
			frappe.throw(_("No file URL provided for conversion to base64."))

		# Get the file document from the URL
		file_doc = None
		if file_url.startswith("/"):
			# It's a file URL like /files/invoice.pdf or /private/files/invoice.pdf
			file_name = file_url.split("/")[-1]
			file_doc = frappe.get_value("File", {"file_url": file_url}, "name")
		else:
			# It might be a file name directly
			file_doc = frappe.get_value("File", {"name": file_url}, "name")

		if not file_doc:
			# Try to find by file_url
			file_doc = frappe.get_value("File", {"file_url": file_url}, "name")

		if not file_doc:
			frappe.throw(_("File not found: {0}").format(file_url))

		file = frappe.get_doc("File", file_doc)

		# Get the full file path
		file_path = file.get_full_path()

		if not file_path:
			frappe.throw(_("Could not resolve file path for: {0}").format(file_url))

		# Read the file and encode to base64
		with open(file_path, "rb") as f:
			file_content = f.read()

		encoded = base64.b64encode(file_content).decode("utf-8")
		
		# Get content type from file metadata, fallback to file extension detection
		mime_type = getattr(file, 'content_type', None)
		if not mime_type:
			file_type = getattr(file, 'file_type', None)
			if file_type:
				# Map Frappe file_type values to MIME types
				file_type_map = {
					'PDF': 'application/pdf',
					'PNG': 'image/png',
					'JPEG': 'image/jpeg',
					'JPG': 'image/jpeg',
					'GIF': 'image/gif',
					'TIFF': 'image/tiff',
					'BMP': 'image/bmp',
					'WEBP': 'image/webp',
					'SVG': 'image/svg+xml',
				}
				mime_type = file_type_map.get(file_type.upper())
		if not mime_type:
			mime_type = "application/octet-stream"

		self._log_debug(
			_("File {0} converted to base64 (type: {1}, size: {2} bytes)").format(
				file_url, mime_type, len(file_content)
			),
			"Invoice Intake AI Client",
		)

		return encoded, mime_type
