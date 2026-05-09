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
	// Remove existing indicators
	frm.dashboard.clear_indicator();

	// Add status-specific indicators
	if (frm.doc.status === 'Processing') {
		frm.dashboard.set_indicator(__('Processing'), 'orange');
	} else if (frm.doc.status === 'Processed') {
		frm.dashboard.set_indicator(__('Processed'), 'green');
	} else if (frm.doc.status === 'Error') {
		frm.dashboard.set_indicator(__('Error'), 'red');
	} else if (frm.doc.status === 'Manual Review Needed') {
		frm.dashboard.set_indicator(__('Manual Review'), 'yellow');
	} else {
		frm.dashboard.set_indicator(__('Pending'), 'blue');
	}
}

function show_progress_indicator(frm) {
	// Show processing log entries if any
	if (frm.doc.error_log && frm.doc.error_log.length > 0) {
		var log_html = '<div class="processing-log">';
		log_html += '<h6>Processing Log:</h6>';
		log_html += '<div class="log-entries">';
		
		frm.doc.error_log.forEach(function(entry) {
			var status_class = entry.status_update.toLowerCase().replace(/\s+/g, '-');
			log_html += '<div class="log-entry ' + status_class + '">';
			log_html += '<span class="timestamp">' + entry.timestamp + '</span>';
			log_html += '<span class="status">' + entry.status_update + '</span>';
			log_html += '<span class="details">' + entry.details + '</span>';
			log_html += '</div>';
		});
		
		log_html += '</div></div>';
		
		frm.dashboard.add_section(log_html, __('Processing Details'));
	}
}
