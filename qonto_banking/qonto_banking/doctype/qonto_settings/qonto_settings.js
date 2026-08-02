// Copyright (c) 2026, itsupport.online and contributors
// For license information, please see license.txt

frappe.ui.form.on("Qonto Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Test Connection"), () => test_connection(frm));
		frm.add_custom_button(__("Link Bank Accounts"), () => link_bank_accounts(frm));
	},
});

// Both actions read the secret through get_password() on the server, so the
// document has to be on disk first. Saving here rather than telling the user to
// save keeps a fresh setup from getting stuck.
function saved(frm) {
	return frm.is_dirty() ? frm.save() : Promise.resolve();
}

function run(frm, method, busy_message, show_result) {
	return saved(frm)
		.then(() => {
			frappe.dom.freeze(busy_message);
			return frm.call(method);
		})
		.then((r) => {
			frappe.dom.unfreeze();
			if (r && r.message) show_result(r.message);
		})
		.catch(() => frappe.dom.unfreeze());
}

function test_connection(frm) {
	run(frm, "test_connection", __("Asking Qonto..."), (result) => {
		const message =
			__("Connected to {0}. Qonto reports {1} bank account(s).", [
				frappe.utils.escape_html(result.organization),
				result.accounts,
			]) + warning_block(result.warnings);

		frappe.msgprint({
			title: __("Connected"),
			indicator: result.warnings && result.warnings.length ? "orange" : "green",
			message: message,
		});
	});
}

function link_bank_accounts(frm) {
	run(frm, "link_bank_accounts", __("Reading your Qonto accounts..."), (result) => {
		frappe.msgprint({
			title: __("Bank accounts"),
			indicator: result.warnings && result.warnings.length ? "orange" : "blue",
			message: build_summary(result),
		});
	});
}

// A ledger account in the wrong currency makes every single transaction fail
// to import, so it is worth shouting about before anyone starts the sync.
function warning_block(warnings) {
	if (!warnings || !warnings.length) return "";

	const items = warnings.map((text) => `<li>${text}</li>`).join("");
	return (
		`<hr><b>${__("Currency does not match")}</b><ul>${items}</ul>` +
		`<p class="text-muted">${__(
			"ERPNext cannot book a transaction into an account kept in another currency. " +
				"Assign a matching account before importing."
		)}</p>`
	);
}

function build_summary(result) {
	const sections = [
		[__("Newly created"), result.created],
		[__("Matched by IBAN"), result.linked],
		[__("Already linked"), result.existing],
	];

	const parts = sections
		.filter(([, accounts]) => accounts && accounts.length)
		.map(([title, accounts]) => {
			const items = accounts
				.map((account) => {
					const currency = account.currency
						? ` <span class="text-muted">(${frappe.utils.escape_html(account.currency)})</span>`
						: "";
					return (
						`<li><a href="/app/bank-account/${encodeURIComponent(account.name)}">` +
						`${frappe.utils.escape_html(account.name)}</a>${currency}</li>`
					);
				})
				.join("");
			return `<b>${title}</b><ul>${items}</ul>`;
		});

	if (!parts.length) {
		return __("Qonto returned no bank accounts.");
	}

	parts.push(
		`<p class="text-muted">${__(
			"Newly created accounts still need an account from your chart of accounts - " +
				"in the currency shown above. Open each one, pick the account and tick " +
				"Is Company Account. The automatic import stays off until then."
		)}</p>`
	);

	return parts.join("") + warning_block(result.warnings);
}
