import frappe
import os
import tempfile
from frappe import _
from PIL import Image


class OCREngine:
	"""Local OCR engine using pytesseract for fallback when AI vision extraction fails.

	Handles both image files (PNG, JPG, etc.) and PDFs by converting them to images
	before running OCR via Tesseract.
	"""

	# Supported image MIME types for direct OCR
	IMAGE_MIME_TYPES = {
		"image/png",
		"image/jpeg",
		"image/jpg",
		"image/tiff",
		"image/bmp",
		"image/webp",
	}

	# PDF MIME types that need conversion first
	PDF_MIME_TYPES = {
		"application/pdf",
	}

	def __init__(self):
		"""Initialize the OCR engine."""
		self._check_dependencies()

	def _check_dependencies(self):
		"""Verify that pytesseract and tesseract binary are available.

		Raises:
			frappe.ValidationError: If dependencies are missing.
		"""
		missing_deps = []
		
		# Check pytesseract Python package
		try:
			import pytesseract
			pytesseract.get_tesseract_version()
		except ImportError:
			missing_deps.append("pytesseract Python package (pip install pytesseract)")
		except Exception as e:
			missing_deps.append(f"tesseract binary not found: {str(e)}")
		
		# Check pdf2image for PDF processing
		try:
			import pdf2image
		except ImportError:
			missing_deps.append("pdf2image Python package (pip install pdf2image)")
		
		# Check PIL/Pillow
		try:
			from PIL import Image
		except ImportError:
			missing_deps.append("Pillow Python package (pip install Pillow)")
		
		if missing_deps:
			install_msg = "\n".join(f"• {dep}" for dep in missing_deps)
			frappe.throw(
				_("OCR dependencies are missing:\n{0}\n\n"
				  "Installation instructions:\n"
				  "• Python packages: pip install pytesseract pdf2image Pillow\n"
				  "• Tesseract binary:\n"
				  "  - Ubuntu/Debian: sudo apt-get install tesseract-ocr\n"
				  "  - CentOS/RHEL: sudo yum install tesseract\n"
				  "  - macOS: brew install tesseract\n"
				  "  - Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki").format(install_msg)
			)

	def _get_file_path(self, file_url):
		"""Resolve a file URL to an absolute file path on disk.

		Args:
			file_url: The URL or path of the file attached to the document.

		Returns:
			The absolute file path as a string.
		"""
		if not file_url:
			frappe.throw(_("No file URL provided for OCR."))

		# Get the file document
		file_doc = None
		if file_url.startswith("/"):
			file_doc = frappe.get_value("File", {"file_url": file_url}, "name")
		else:
			file_doc = frappe.get_value("File", {"name": file_url}, "name")

		if not file_doc:
			file_doc = frappe.get_value("File", {"file_url": file_url}, "name")

		if not file_doc:
			frappe.throw(_("File not found: {0}").format(file_url))

		file = frappe.get_doc("File", file_doc)
		file_path = file.get_full_path()

		if not file_path or not os.path.exists(file_path):
			frappe.throw(_("File not found on disk: {0}").format(file_url))

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

		return file_path, mime_type

	def _ocr_image(self, image_path):
		"""Run Tesseract OCR on a single image file.

		Args:
			image_path: Path to the image file.

		Returns:
			The extracted text as a string.
		"""
		import pytesseract

		try:
			image = Image.open(image_path)
			# Convert to RGB if necessary (e.g. for PNG with alpha channel)
			if image.mode in ("RGBA", "LA", "P"):
				image = image.convert("RGB")

			# Run OCR with English language
			text = pytesseract.image_to_string(
				image,
				lang="eng",
				config="--psm 6 --oem 3",  # Assume uniform block of text, LSTM engine
			)
			return text.strip()

		except Exception as e:
			frappe.logger(__name__).error(
				_("OCR failed on image {0}: {1}").format(image_path, str(e))
			)
			raise

	def _ocr_pdf(self, pdf_path):
		"""Convert a PDF to images and run OCR on each page.

		Args:
			pdf_path: Path to the PDF file.

		Returns:
			The concatenated extracted text from all pages.
		"""
		from pdf2image import convert_from_path

		try:
			# Convert PDF to images (300 DPI for good OCR quality)
			images = convert_from_path(pdf_path, dpi=300)

			if not images:
				return ""

			all_text = []
			for i, image in enumerate(images):
				# Save each page as a temp image for OCR
				with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
					tmp_path = tmp.name
					image.save(tmp_path, "PNG")

				try:
					page_text = self._ocr_image(tmp_path)
					if page_text:
						all_text.append(_("--- Page {0} ---").format(i + 1))
						all_text.append(page_text)
				finally:
					# Clean up temp file
					try:
						os.unlink(tmp_path)
					except OSError:
						pass

			return "\n".join(all_text)

		except Exception as e:
			frappe.logger(__name__).error(
				_("OCR failed on PDF {0}: {1}").format(pdf_path, str(e))
			)
			raise

	def extract_text(self, file_url):
		"""Extract text from a file using OCR.

		Automatically detects whether the file is an image or PDF and
		runs the appropriate OCR pipeline.

		Args:
			file_url: The URL or path of the file to OCR.

		Returns:
			The extracted text as a string, or None if OCR fails.
		"""
		try:
			file_path, mime_type = self._get_file_path(file_url)

			frappe.logger(__name__).debug(
				_("Starting OCR for file: {0} (type: {1})").format(file_url, mime_type)
			)

			# Determine the MIME type from file extension if not provided
			if not mime_type or mime_type == "application/octet-stream":
				ext = os.path.splitext(file_path)[1].lower()
				if ext in (".png",):
					mime_type = "image/png"
				elif ext in (".jpg", ".jpeg"):
					mime_type = "image/jpeg"
				elif ext in (".tiff", ".tif"):
					mime_type = "image/tiff"
				elif ext in (".bmp",):
					mime_type = "image/bmp"
				elif ext in (".webp",):
					mime_type = "image/webp"
				elif ext in (".pdf",):
					mime_type = "application/pdf"

			# Run OCR based on file type
			if mime_type in self.IMAGE_MIME_TYPES:
				text = self._ocr_image(file_path)
			elif mime_type in self.PDF_MIME_TYPES:
				text = self._ocr_pdf(file_path)
			else:
				# Try as image anyway
				frappe.logger(__name__).warning(
					_("Unknown MIME type {0}, attempting image OCR on {1}").format(
						mime_type, file_path
					)
				)
				text = self._ocr_image(file_path)

			if text:
				frappe.logger(__name__).debug(
					_("OCR extracted {0} characters from {1}").format(len(text), file_url)
				)
			else:
				frappe.logger(__name__).warning(
					_("OCR returned empty text for {0}").format(file_url)
				)

			return text if text else None

		except Exception as e:
			frappe.logger(__name__).error(
				_("OCR extraction failed for {0}: {1}").format(file_url, str(e))
			)
			return None
