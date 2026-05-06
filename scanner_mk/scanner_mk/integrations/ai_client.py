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
		"""Log a debug message to the Error Log only if debug logging is enabled.

		Args:
			message: The message to log.
			method: The method name for the Error Log.
		"""
		if self._is_debug_logging_enabled():
			frappe.log_error(message, method)

	def _log_error_always(self, message, method="Invoice Intake AI Client"):
		"""Log an error message to the Error Log ALWAYS (regardless of debug setting).

		This should be used for actual failures and errors, not debug info.
		Debug-level messages should use _log_debug instead.

		Args:
			message: The error message to log.
			method: The method name for the Error Log.
		"""
		frappe.log_error(message, method)

	def _log_progress(self, intake_log_name, status_update, details):
		"""Log a progress entry to the Intake Processing Log child table.

		This always writes to the child table so users can see processing steps
		in the Invoice Intake Log form. Also logs to Error Log if debug logging is enabled.

		Args:
			intake_log_name: The name of the Invoice Intake Log document.
			status_update: A short status update string.
			details: Detailed description.
		"""
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

	def _get_file_as_base64(self, file_url):
		"""Convert an attached file to base64 encoded string.

		Args:
			file_url: The URL or path of the file attached to the document.

		Returns:
			A tuple of (base64_encoded_string, mime_type).
		"""
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

	def _build_prompt(self, for_text=False):
		"""Construct the prompt asking the AI to extract invoice data in strict JSON format.

		Args:
			for_text: If True, builds a prompt for text-based extraction (OCR fallback).
			          If False, builds a prompt for vision-based extraction.

		Returns:
			A string containing the system and user prompt.
		"""
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
				"{{"
				f'\n  "vendor_name": "{vendor_desc}",\n'
				'  "date": "string (invoice date in YYYY-MM-DD format)",\n'
				'  "invoice_number": "string (the invoice number)",\n'
				'  "currency": "string (the currency code e.g. USD, HKD, EUR, CNY, THB, KRW, JPY - use ISO 4217 3-letter code)",\n'
				'  "items": [\n'
				"    {{\n"
				f'      "description": "{item_desc}",\n'
				'      "qty": number (quantity as a number),\n'
				'      "rate": number (unit rate/price as a number)\n'
				"    }}\n"
				"  ],\n"
				'  "totals": {{\n'
				'    "subtotal": number (subtotal before tax),\n'
				'    "tax": number (total tax amount),\n'
				'    "grand_total": number (total including tax)\n'
				"  }}\n"
				"}}\n\n"
				"If any field is not found in the text, use null for that field. "
				"For items, extract all line items mentioned. "
				"If no items are found, return an empty array for items.\n\n"
				"--- OCR TEXT START ---\n"
				"{ocr_text}\n"
				"--- OCR TEXT END ---"
			)
		else:
			user_prompt = (
				"Extract the following information from this invoice image and return it as a strict JSON object. "
				"The invoice may be in any language (English, Chinese, Thai, Korean, Japanese, etc.). "
				f"{translation_instruction} "
				"Do NOT include any markdown formatting, code blocks, or extra text. Return ONLY the raw JSON object.\n\n"
				"Required JSON schema:\n"
				"{{"
				f'\n  "vendor_name": "{vendor_desc}",\n'
				'  "date": "string (invoice date in YYYY-MM-DD format)",\n'
				'  "invoice_number": "string (the invoice number)",\n'
				'  "currency": "string (the currency code e.g. USD, HKD, EUR, CNY, THB, KRW, JPY - use ISO 4217 3-letter code)",\n'
				'  "items": [\n'
				"    {{\n"
				f'      "description": "{item_desc}",\n'
				'      "qty": number (quantity as a number),\n'
				'      "rate": number (unit rate/price as a number)\n'
				"    }}\n"
				"  ],\n"
				'  "totals": {{\n'
				'    "subtotal": number (subtotal before tax),\n'
				'    "tax": number (total tax amount),\n'
				'    "grand_total": number (total including tax)\n'
				"  }}\n"
				"}}\n\n"
				"If any field is not found in the invoice, use null for that field. "
				"For items, extract all line items listed on the invoice. "
				"If no items are found, return an empty array for items."
			)

		return [
			{"role": "system", "content": system_prompt},
			{"role": "user", "content": user_prompt},
		]

	def _build_messages_with_text(self, ocr_text):
		"""Build the messages payload using OCR-extracted text for text-only models.

		Args:
			ocr_text: The text extracted by the local OCR engine.

		Returns:
			A list of message dicts suitable for the API request.
		"""
		prompt_messages = self._build_prompt(for_text=True)

		# Inject the OCR text into the user prompt
		for msg in prompt_messages:
			if msg["role"] == "user":
				msg["content"] = msg["content"].format(ocr_text=ocr_text)

		self._log_debug(
			_("Built text-based messages with {0} chars of OCR text").format(len(ocr_text)),
			"Invoice Intake AI Client",
		)

		return prompt_messages

	def _build_messages_with_image(self, base64_image, mime_type):
		"""Build the messages payload including the image for vision-capable models.

		Args:
			base64_image: The base64-encoded image content.
			mime_type: The MIME type of the image (e.g., image/png, image/jpeg, application/pdf).

		Returns:
			A list of message dicts suitable for the API request.
		"""
		prompt_messages = self._build_prompt()

		# Add the image to the user message content
		# For vision models, we need to send the image as a data URL in the content
		image_data_url = f"data:{mime_type};base64,{base64_image}"

		# Replace the user message content to include the image
		for msg in prompt_messages:
			if msg["role"] == "user":
				msg["content"] = [
					{"type": "text", "text": msg["content"]},
					{
						"type": "image_url",
						"image_url": {"url": image_data_url},
					},
				]

		self._log_debug(
			_("Built vision messages with MIME type: {0}").format(mime_type),
			"Invoice Intake AI Client",
		)

		return prompt_messages

	def _call_deepseek_api(self, messages):
		"""Call the DeepSeek API.

		Args:
			messages: The messages payload for the API request.

		Returns:
			The JSON response from the API.
		"""
		if not self.api_key:
			frappe.throw(_("DeepSeek API Key is not configured in Invoice Intake Settings."))

		headers = {
			"Authorization": f"Bearer {self.api_key}",
			"Content-Type": "application/json",
		}

		payload = {
			"model": "deepseek-vl2",
			"messages": messages,
			"max_tokens": 4096,
			"temperature": 0.1,
		}

		self._log_debug(
			_("Calling DeepSeek API with model deepseek-vl2"),
			"Invoice Intake AI Client",
		)

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
			frappe.log_error(error_msg, "Invoice Intake AI Client")
			frappe.throw(error_msg)

		self._log_debug(
			_("DeepSeek API responded successfully (HTTP 200)"),
			"Invoice Intake AI Client",
		)

		return response.json()

	def _call_openrouter_api(self, messages):
		"""Call the OpenRouter API.

		Args:
			messages: The messages payload for the API request.

		Returns:
			The JSON response from the API.
		"""
		if not self.api_key:
			frappe.throw(_("OpenRouter API Key is not configured in Invoice Intake Settings."))

		model = self.openrouter_model or "google/gemini-2.0-flash-001"

		headers = {
			"Authorization": f"Bearer {self.api_key}",
			"Content-Type": "application/json",
			"HTTP-Referer": frappe.utils.get_url() or "https://tik13.org",
			"X-Title": "Invoice Intake Scanner MK",
		}

		payload = {
			"model": model,
			"messages": messages,
			"max_tokens": 4096,
			"temperature": 0.1,
		}

		self._log_debug(
			_("Calling OpenRouter API with model {0}").format(model),
			"Invoice Intake AI Client",
		)

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
			frappe.log_error(error_msg, "Invoice Intake AI Client")
			frappe.throw(error_msg)

		self._log_debug(
			_("OpenRouter API responded successfully (HTTP 200)"),
			"Invoice Intake AI Client",
		)

		return response.json()

	def _call_local_llm_api(self, messages):
		"""Call a local LLM API (e.g. Ollama, LM Studio, vLLM) using an OpenAI-compatible endpoint.

		Args:
			messages: The messages payload for the API request.

		Returns:
			The JSON response from the local API.
		"""
		if not self.local_llm_endpoint:
			frappe.throw(_("Local LLM Endpoint URL is not configured in Invoice Intake Settings."))

		if not self.local_llm_model:
			frappe.throw(_("Local LLM Model is not configured in Invoice Intake Settings."))

		headers = {
			"Content-Type": "application/json",
		}

		# Add API key header if one is configured (some local servers require it)
		if self.api_key:
			headers["Authorization"] = f"Bearer {self.api_key}"

		payload = {
			"model": self.local_llm_model,
			"messages": messages,
			"max_tokens": 4096,
			"temperature": 0.1,
			"stream": False,
		}

		self._log_debug(
			_("Calling Local LLM API at {0} with model {1}").format(
				self.local_llm_endpoint, self.local_llm_model
			),
			"Invoice Intake AI Client",
		)

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
			frappe.log_error(error_msg, "Invoice Intake AI Client")
			frappe.throw(error_msg)

		self._log_debug(
			_("Local LLM API responded successfully (HTTP 200)"),
			"Invoice Intake AI Client",
		)

		return response.json()

	def _call_api(self, messages):
		"""Call the configured AI API provider.

		Args:
			messages: The messages payload for the API request.

		Returns:
			The raw text response from the AI model.
		"""
		if self.api_provider == "DeepSeek VL":
			response = self._call_deepseek_api(messages)
		elif self.api_provider == "OpenRouter":
			response = self._call_openrouter_api(messages)
		elif self.api_provider == "Local LLM":
			response = self._call_local_llm_api(messages)
		else:
			frappe.throw(_("Unsupported API provider: {0}").format(self.api_provider))

		# Extract the content from the response
		try:
			content = response["choices"][0]["message"]["content"]
			if content is None:
				self._log_error_always(
					_("API returned null content. Response keys: {0}").format(
						list(response.keys()) if isinstance(response, dict) else type(response).__name__
					),
					"Invoice Intake AI Client",
				)
				raise ValueError("API returned null content")
			self._log_debug(
				_("API response content length: {0} chars").format(len(content)),
				"Invoice Intake AI Client",
			)
			return content
		except (KeyError, IndexError, TypeError) as e:
			self._log_error_always(
				_("Unexpected API response structure: {0}. Response keys: {1}").format(
					str(e), list(response.keys()) if isinstance(response, dict) else type(response).__name__
				),
				"Invoice Intake AI Client",
			)
			raise

	def _parse_json_response(self, response_text):
		"""Parse the JSON response from the AI model.

		Args:
			response_text: The raw text response from the AI model.

		Returns:
			A parsed JSON dictionary.

		Raises:
			json.JSONDecodeError: If the response is not valid JSON.
		"""
		if not response_text or not response_text.strip():
			self._log_debug(
				_("Empty response from AI model"),
				"Invoice Intake AI Client",
			)
			raise json.JSONDecodeError("Empty response from AI model", "", 0)

		# Clean the response text - remove any markdown code block markers if present
		cleaned = response_text.strip()

		# Remove markdown code block markers if present
		if cleaned.startswith("```json"):
			cleaned = cleaned[7:]
		elif cleaned.startswith("```"):
			cleaned = cleaned[3:]

		if cleaned.endswith("```"):
			cleaned = cleaned[:-3]

		cleaned = cleaned.strip()

		# Remove leading newlines and whitespace
		cleaned = cleaned.lstrip("\n\r\t ")

		self._log_debug(
			_("Parsing AI response. Original: {0} chars, Cleaned: {1} chars").format(
				len(response_text), len(cleaned)
			),
			"Invoice Intake AI Client",
		)

		# Try to parse as-is first
		try:
			result = json.loads(cleaned)
			self._log_debug(
				_("AI response parsed successfully (direct parse)"),
				"Invoice Intake AI Client",
			)
			return result
		except json.JSONDecodeError:
			pass

		# If the response doesn't start with '{', try to find a JSON object
		if not cleaned.startswith("{"):
			# Try to find where the JSON object starts
			brace_idx = cleaned.find("{")
			if brace_idx >= 0:
				cleaned = cleaned[brace_idx:]
				try:
					result = json.loads(cleaned)
					self._log_debug(
						_("AI response parsed successfully (found JSON object at index {0})").format(brace_idx),
						"Invoice Intake AI Client",
					)
					return result
				except json.JSONDecodeError:
					pass

			# Try wrapping the whole thing in braces (handles missing opening brace)
			# e.g. '\n  "vendor_name": "..."' -> '{"vendor_name": "..."}'
			cleaned = "{" + cleaned + "}"
			try:
				result = json.loads(cleaned)
				self._log_debug(
					_("AI response parsed successfully (wrapped in braces)"),
					"Invoice Intake AI Client",
				)
				return result
			except json.JSONDecodeError:
				pass

		# If all else fails, raise a clear error
		self._log_debug(
			_("Failed to parse AI response as JSON. First 500 chars: {0}").format(response_text[:500]),
			"Invoice Intake AI Client",
		)
		raise json.JSONDecodeError(
			f"Failed to parse AI response as JSON. Response text: {response_text[:500]}",
			response_text,
			0
		)

	def _extract_with_vision(self, file_url, intake_log_name=None):
		"""Attempt extraction using vision-based AI (image sent directly to the model).

		This is the primary extraction path.

		Args:
			file_url: The URL of the file attached to the Invoice Intake Log.
			intake_log_name: Optional name of the Invoice Intake Log document for logging.

		Returns:
			Extracted data dict, or None if vision extraction fails.
		"""
		self._log_progress(
			intake_log_name,
			"Vision Extraction",
			_("Starting vision-based AI extraction for {0}").format(file_url),
		)

		try:
			base64_image, mime_type = self._get_file_as_base64(file_url)
			messages = self._build_messages_with_image(base64_image, mime_type)
			response_text = self._call_api(messages)

			self._log_debug(
				_("Vision AI raw response: {0}").format(response_text[:500]),
				"Invoice Intake AI Client",
			)

			extracted_data = self._parse_json_response(response_text)
			self._validate_extracted_data(extracted_data)

			self._log_progress(
				intake_log_name,
				"Vision Extraction Succeeded",
				_("Successfully extracted data via vision AI. Vendor: {0}, Invoice: {1}").format(
					extracted_data.get("vendor_name", "N/A"),
					extracted_data.get("invoice_number", "N/A"),
				),
			)

			self._log_debug(
				_("Vision extraction succeeded for {0}").format(file_url),
				"Invoice Intake AI Client",
			)
			return extracted_data

		except (json.JSONDecodeError, ValueError) as e:
			self._log_progress(
				intake_log_name,
				"Vision Extraction Failed",
				_("Parse/validation error: {0}").format(str(e)[:200]),
			)
			self._log_error_always(
				_("Vision extraction failed (parse/validation error): {0}").format(str(e)),
				"Invoice Intake AI Client",
			)
			return None
		except requests.exceptions.RequestException as e:
			self._log_progress(
				intake_log_name,
				"Vision Extraction Failed",
				_("API error: {0}").format(str(e)[:200]),
			)
			self._log_error_always(
				_("Vision extraction failed (API error): {0}").format(str(e)),
				"Invoice Intake AI Client",
			)
			return None
		except Exception as e:
			self._log_progress(
				intake_log_name,
				"Vision Extraction Failed",
				_("Unexpected error: {0}").format(str(e)[:200]),
			)
			self._log_error_always(
				_("Vision extraction failed (unexpected): {0}\n{1}").format(
					str(e), frappe.get_traceback()
				),
				"Invoice Intake AI Client",
			)
			return None

	def _extract_with_ocr_fallback(self, file_url, intake_log_name=None):
		"""Fallback: Run local OCR on the file, then send the extracted text to the AI for structuring.

		Args:
			file_url: The URL of the file attached to the Invoice Intake Log.
			intake_log_name: Optional name of the Invoice Intake Log document for logging.

		Returns:
			Extracted data dict, or None if OCR+AI extraction also fails.
		"""
		self._log_progress(
			intake_log_name,
			"OCR Fallback",
			_("Starting local OCR + AI structuring for {0}").format(file_url),
		)

		try:
			# Step 1: Run local OCR
			from erpnext_scanner_mk.utils.ocr import OCREngine

			ocr = OCREngine()
			ocr_text = ocr.extract_text(file_url)

			if not ocr_text:
				self._log_progress(
					intake_log_name,
					"OCR Failed",
					_("OCR returned no text for {0}").format(file_url),
				)
				self._log_debug(
					_("OCR returned no text for {0}").format(file_url),
					"Invoice Intake AI Client",
				)
				return None

			self._log_progress(
				intake_log_name,
				"OCR Completed",
				_("OCR extracted {0} characters from {1}").format(len(ocr_text), file_url),
			)

			self._log_debug(
				_("OCR extracted text ({0} chars): {1}").format(
					len(ocr_text), ocr_text[:500]
				),
				"Invoice Intake AI Client",
			)

			# Step 2: Build text-based messages with OCR output
			messages = self._build_messages_with_text(ocr_text)

			# Step 3: Send to AI for structuring
			response_text = self._call_api(messages)

			self._log_debug(
				_("OCR+AI raw response: {0}").format(response_text[:500]),
				"Invoice Intake AI Client",
			)

			extracted_data = self._parse_json_response(response_text)
			self._validate_extracted_data(extracted_data)

			self._log_progress(
				intake_log_name,
				"OCR+AI Extraction Succeeded",
				_("Successfully extracted data via OCR + AI. Vendor: {0}, Invoice: {1}").format(
					extracted_data.get("vendor_name", "N/A"),
					extracted_data.get("invoice_number", "N/A"),
				),
			)

			self._log_debug(
				_("OCR+AI extraction succeeded for {0}").format(file_url),
				"Invoice Intake AI Client",
			)
			return extracted_data

		except (json.JSONDecodeError, ValueError) as e:
			self._log_progress(
				intake_log_name,
				"OCR+AI Extraction Failed",
				_("Parse/validation error: {0}").format(str(e)[:200]),
			)
			self._log_error_always(
				_("OCR+AI extraction failed (parse/validation error): {0}").format(str(e)),
				"Invoice Intake AI Client",
			)
			return None
		except requests.exceptions.RequestException as e:
			self._log_progress(
				intake_log_name,
				"OCR+AI Extraction Failed",
				_("API error: {0}").format(str(e)[:200]),
			)
			self._log_error_always(
				_("OCR+AI extraction failed (API error): {0}").format(str(e)),
				"Invoice Intake AI Client",
			)
			return None
		except Exception as e:
			self._log_progress(
				intake_log_name,
				"OCR+AI Extraction Failed",
				_("Unexpected error: {0}").format(str(e)[:200]),
			)
			self._log_error_always(
				_("OCR+AI extraction failed (unexpected): {0}\n{1}").format(
					str(e), frappe.get_traceback()
				),
				"Invoice Intake AI Client",
			)
			return None

	def _set_manual_review(self, intake_log_name, reason):
		"""Set the intake log to 'Manual Review Needed' and create a Frappe ToDo for the user.

		Args:
			intake_log_name: The name of the Invoice Intake Log document.
			reason: The reason why manual review is needed.
		"""
		if not intake_log_name:
			return

		try:
			intake_log = frappe.get_doc("Invoice Intake Log", intake_log_name)

			# Set status to Manual Review Needed
			intake_log.status = "Manual Review Needed"

			# Add a log entry
			row = intake_log.append("error_log", {})
			row.timestamp = frappe.utils.now()
			row.status_update = _("Manual Review Needed")
			row.details = reason

			intake_log.save(ignore_permissions=True)
			frappe.db.commit()

			# Create a Frappe ToDo for the user
			todo = frappe.get_doc({
				"doctype": "ToDo",
				"description": _(
					"Invoice Intake Log {0} requires manual review.\n\n"
					"Reason: {1}\n\n"
					"Please review the attached invoice and process it manually."
				).format(intake_log_name, reason),
				"reference_type": "Invoice Intake Log",
				"reference_name": intake_log_name,
				"status": "Open",
				"priority": "Medium",
			})
			todo.insert(ignore_permissions=True)
			frappe.db.commit()

			self._log_debug(
				_("Set {0} to Manual Review Needed and created ToDo").format(intake_log_name),
				"Invoice Intake AI Client",
			)

		except Exception as e:
			self._log_debug(
				_("Failed to set manual review for {0}: {1}").format(intake_log_name, str(e)),
				"Invoice Intake AI Client",
			)

	def extract_invoice_data(self, file_url, intake_log_name=None):
		"""Extract invoice data from an attached file using the configured AI API.

		Extraction pipeline with automatic fallback:
		1. Try vision-based AI extraction (send image directly to the model)
		2. If vision fails, run local OCR (pytesseract) and send text to AI for structuring
		3. If OCR+AI also fails, set status to 'Manual Review Needed' and create a ToDo

		Args:
			file_url: The URL of the file attached to the Invoice Intake Log.
			intake_log_name: Optional name of the Invoice Intake Log document for logging errors.

		Returns:
			A dictionary containing the extracted invoice data with keys:
				vendor_name, date, invoice_number, items, totals.
				Returns None if all extraction methods fail.

		Raises:
			frappe.ValidationError: If configuration is invalid.
		"""
		try:
			self._log_progress(
				intake_log_name,
				"Pipeline Started",
				_("Starting AI extraction pipeline for file: {0}").format(file_url),
			)

			self._log_debug(
				_("Starting AI extraction for file: {0} (intake log: {1})").format(
					file_url, intake_log_name
				),
				"Invoice Intake AI Client",
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

			self._log_debug(
				_("All extraction methods failed for {0}. Set to Manual Review Needed.").format(file_url),
				"Invoice Intake AI Client",
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

	def _validate_extracted_data(self, data):
		"""Validate that the extracted data has the expected structure.

		Args:
			data: The parsed JSON data to validate.

		Raises:
			ValueError: If the data structure is invalid.
		"""
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

	def _log_error(self, intake_log_name, status_update, details):
		"""Log an error to the Intake Processing Log child table and set parent status to 'Error'.

		Args:
			intake_log_name: The name of the Invoice Intake Log document.
			status_update: A short status update string.
			details: Detailed error description.
		"""
		if not intake_log_name:
			self._log_debug(
				_("AI Client Error (no intake log): {0} - {1}").format(status_update, details),
				"Invoice Intake AI Client",
			)
			return

		try:
			intake_log = frappe.get_doc("Invoice Intake Log", intake_log_name)

			# Add log entry to the child table
			row = intake_log.append("error_log", {})
			row.timestamp = frappe.utils.now()
			row.status_update = status_update
			row.details = details

			# Set parent status to Error
			intake_log.status = "Error"

			intake_log.save(ignore_permissions=True)
			frappe.db.commit()

		except Exception as e:
			self._log_debug(
				_("Failed to log error to intake log {0}: {1}").format(intake_log_name, str(e)),
				"Invoice Intake AI Client",
			)
