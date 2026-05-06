"""Test script for the Invoice Intake pipeline.

Run this from the bench console:
    bench --site test.tik13.org console
    exec(open('apps/erpnext_scanner_mk/scanner_mk/utils/test_pipeline.py').read())

Or run individual tests:
    bench --site test.tik13.org console
    from erpnext_scanner_mk.utils.test_pipeline import *
    test_ocr_engine()
    test_ai_client()
    test_full_pipeline()
"""

import frappe
import json
import os
from frappe import _


def test_ocr_engine():
	"""Test the OCR engine directly with a sample file."""
	print("\n" + "=" * 60)
	print("TEST 1: OCR Engine")
	print("=" * 60)

	from erpnext_scanner_mk.utils.ocr import OCREngine

	# Find any file attached to an Invoice Intake Log
	intake_logs = frappe.get_all(
		"Invoice Intake Log",
		filters={"invoice_attachment": ["is", "set"]},
		fields=["name", "invoice_attachment"],
		limit=1,
	)

	if not intake_logs:
		print("⚠️  No Invoice Intake Logs with attachments found.")
		print("   Create one first via the UI, then re-run this test.")
		return

	log = intake_logs[0]
	print(f"📄 Testing OCR on: {log.name}")
	print(f"   File: {log.invoice_attachment}")

	ocr = OCREngine()
	text = ocr.extract_text(log.invoice_attachment)

	if text:
		print(f"✅ OCR succeeded! Extracted {len(text)} characters.")
		print(f"\n--- First 500 chars of OCR output ---")
		print(text[:500])
		print("...")
	else:
		print("❌ OCR returned no text.")

	return text


def test_ai_client_vision():
	"""Test the AI client's vision extraction directly."""
	print("\n" + "=" * 60)
	print("TEST 2: AI Client - Vision Extraction")
	print("=" * 60)

	from erpnext_scanner_mk.integrations.ai_client import AIClient

	# Find any file attached to an Invoice Intake Log
	intake_logs = frappe.get_all(
		"Invoice Intake Log",
		filters={"invoice_attachment": ["is", "set"]},
		fields=["name", "invoice_attachment"],
		limit=1,
	)

	if not intake_logs:
		print("⚠️  No Invoice Intake Logs with attachments found.")
		return

	log = intake_logs[0]
	print(f"🤖 Testing Vision AI on: {log.name}")
	print(f"   File: {log.invoice_attachment}")

	client = AIClient()
	data = client._extract_with_vision(log.invoice_attachment, intake_log_name=log.name)

	if data:
		print(f"✅ Vision extraction succeeded!")
		print(f"\n--- Extracted Data ---")
		print(json.dumps(data, indent=2))
	else:
		print("❌ Vision extraction failed (will fall back to OCR).")

	return data


def test_ai_client_ocr_fallback():
	"""Test the AI client's OCR fallback extraction directly."""
	print("\n" + "=" * 60)
	print("TEST 3: AI Client - OCR Fallback Extraction")
	print("=" * 60)

	from erpnext_scanner_mk.integrations.ai_client import AIClient

	# Find any file attached to an Invoice Intake Log
	intake_logs = frappe.get_all(
		"Invoice Intake Log",
		filters={"invoice_attachment": ["is", "set"]},
		fields=["name", "invoice_attachment"],
		limit=1,
	)

	if not intake_logs:
		print("⚠️  No Invoice Intake Logs with attachments found.")
		return

	log = intake_logs[0]
	print(f"🔍 Testing OCR+AI on: {log.name}")
	print(f"   File: {log.invoice_attachment}")

	client = AIClient()
	data = client._extract_with_ocr_fallback(log.invoice_attachment, intake_log_name=log.name)

	if data:
		print(f"✅ OCR+AI extraction succeeded!")
		print(f"\n--- Extracted Data ---")
		print(json.dumps(data, indent=2))
	else:
		print("❌ OCR+AI extraction failed.")

	return data


def test_full_pipeline():
	"""Test the full extraction pipeline (vision -> OCR fallback -> manual review)."""
	print("\n" + "=" * 60)
	print("TEST 4: Full Extraction Pipeline")
	print("=" * 60)

	from erpnext_scanner_mk.integrations.ai_client import AIClient

	# Find any file attached to an Invoice Intake Log
	intake_logs = frappe.get_all(
		"Invoice Intake Log",
		filters={"invoice_attachment": ["is", "set"]},
		fields=["name", "invoice_attachment"],
		limit=1,
	)

	if not intake_logs:
		print("⚠️  No Invoice Intake Logs with attachments found.")
		return

	log = intake_logs[0]
	print(f"🚀 Testing full pipeline on: {log.name}")
	print(f"   File: {log.invoice_attachment}")

	client = AIClient()
	data = client.extract_invoice_data(log.invoice_attachment, intake_log_name=log.name)

	if data:
		print(f"✅ Pipeline succeeded!")
		print(f"\n--- Extracted Data ---")
		print(json.dumps(data, indent=2))
	else:
		print("❌ Pipeline returned None (check if status was set to Manual Review Needed).")

	# Check the intake log status
	intake_log = frappe.get_doc("Invoice Intake Log", log.name)
	print(f"\n📊 Final status: {intake_log.status}")
	print(f"   Processing logs:")
	for entry in intake_log.error_log:
		print(f"   - [{entry.timestamp}] {entry.status_update}: {entry.details}")

	return data


def test_create_sample_intake_log():
	"""Create a sample Invoice Intake Log with a test file for manual testing."""
	print("\n" + "=" * 60)
	print("TEST SETUP: Create Sample Invoice Intake Log")
	print("=" * 60)

	# Check if there's a sample invoice file in the site's public files
	sample_files = frappe.get_all(
		"File",
		filters={"file_name": ["like", "%invoice%"]},
		fields=["name", "file_url", "file_name"],
		limit=5,
	)

	if sample_files:
		print(f"Found {len(sample_files)} existing invoice files:")
		for f in sample_files:
			print(f"   - {f.file_name} ({f.file_url})")

		# Create an intake log with the first one
		file_doc = sample_files[0]
		intake_log = frappe.get_doc({
			"doctype": "Invoice Intake Log",
			"invoice_attachment": file_doc.file_url,
			"status": "Pending",
		})
		intake_log.insert(ignore_permissions=True)
		frappe.db.commit()
		print(f"\n✅ Created Invoice Intake Log: {intake_log.name}")
		print(f"   Status: {intake_log.status}")
		print(f"   File: {intake_log.invoice_attachment}")
		return intake_log.name
	else:
		print("⚠️  No sample invoice files found.")
		print("   Upload an invoice file via the UI first:")
		print("   1. Go to the Invoice Intake Log list")
		print("   2. Click 'Add Invoice Intake Log'")
		print("   3. Attach an invoice PDF/image")
		print("   4. Save")
		return None


def run_all_tests():
	"""Run all tests in sequence."""
	print("\n" + "🌟" * 30)
	print("🌟  INVOICE INTAKE PIPELINE TEST SUITE")
	print("🌟" * 30)

	test_ocr_engine()
	test_ai_client_vision()
	test_ai_client_ocr_fallback()
	test_full_pipeline()

	print("\n" + "=" * 60)
	print("✅ ALL TESTS COMPLETE")
	print("=" * 60)


if __name__ == "__main__":
	run_all_tests()
