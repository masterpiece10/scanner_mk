frappe.ui.form.on('Invoice Intake Log', {
	refresh: function(frm) {
		// Add the "Process Now" button for eligible statuses
		if (!frm.is_new() && ["Pending", "Error", "Manual Review Needed"].includes(frm.doc.status)) {
			frm.add_custom_button(__('Process Now'), function() {
				frm.call({
					doc: frm.doc,
					method: 'process_now',
					args: {
						doc_name: frm.doc.name
					},
					callback: function(r) {
						if (r.message) {
							frappe.msgprint(r.message);
							frm.reload_doc();
						}
					},
					error: function(r) {
						frappe.msgprint(__('Error triggering processing: ') + r.message);
					}
				});
			}, __('Actions'));
		}

		// Show a status indicator badge
		set_status_indicator(frm);

		// Set up auto-refresh for Processing status
		if (frm.doc.status === 'Processing') {
			frm.dashboard.set_headline(__('⏳ Processing in progress... Please wait.'));
			// Auto-refresh every 5 seconds while processing
			setTimeout(function() {
				frm.reload_doc();
			}, 5000);
		} else if (frm.doc.status === 'Processed') {
			frm.dashboard.set_headline(__('✅ Processing complete. Purchase Invoice created.'));
		} else if (frm.doc.status === 'Error') {
			frm.dashboard.set_headline(__('❌ Processing encountered an error. Check the Processing Log for details.'));
		} else if (frm.doc.status === 'Manual Review Needed') {
			frm.dashboard.set_headline(__('⚠️ This invoice requires manual review.'));
		} else if (frm.doc.status === 'Pending') {
			frm.dashboard.set_headline(__('⏸️ Pending processing. Click "Process Now" to start.'));
		}

		// Show a progress indicator in the dashboard
		show_progress_indicator(frm);
	}
});

function set_status_indicator(frm) {
	var status_map = {
		"Pending": { label: __("Pending"), color: "orange" },
		"Processing": { label: __("Processing"), color: "blue" },
		"Processed": { label: __("Processed"), color: "green" },
		"Error": { label: __("Error"), color: "red" },
		"Manual Review Needed": { label: __("Manual Review Needed"), color: "yellow" }
	};

	var status = status_map[frm.doc.status];
	if (status) {
		frm.set_indicator(status.label, status.color);
	}
}

function show_progress_indicator(frm) {
	// Show a progress bar based on status
	var progress = 0;
	var message = '';

	switch (frm.doc.status) {
		case 'Pending':
			progress = 0;
			message = __('Waiting to start...');
			break;
		case 'Processing':
			progress = 50;
			message = __('AI extraction and mapping in progress...');
			break;
		case 'Processed':
			progress = 100;
			message = __('Purchase Invoice created successfully.');
			break;
		case 'Error':
			progress = 0;
			message = __('Processing failed. See log for details.');
			break;
		case 'Manual Review Needed':
			progress = 75;
			message = __('Data extracted, needs manual review.');
			break;
		default:
			return;
	}

	frm.dashboard.show_progress(__('Processing Progress'), progress, message);
}
