// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("CRM Data Erasure Request", {
  refresh(frm) {
    if (frm.is_new() || frm.doc.status !== "Pending Approval") return;

    const isPrivacy = frappe.user.has_role("CRM Privacy Officer");
    const loggedIt = [frm.doc.requested_by, frm.doc.owner].includes(
      frappe.session.user,
    );

    if (!isPrivacy) return;
    if (loggedIt) {
      frm.dashboard.set_headline(
        __(
          "You logged this request, so someone else on the Privacy team has to approve it.",
        ),
        "orange",
      );
      return;
    }

    frm.add_custom_button(__("Preview"), () => showPreview(frm));
    frm.add_custom_button(__("Reject"), () => reject(frm));
    frm
      .add_custom_button(__("Approve & Erase"), () => approve(frm))
      .addClass("btn-danger");
  },
});

function previewHtml(preview, requestName) {
  const rows = Object.entries(preview.counts)
    .filter(([, count]) => count)
    .map(
      ([doctype, count]) =>
        `<tr><td>${__(doctype)}</td><td class="text-right">${count}</td></tr>`,
    )
    .join("");
  const list = (label, names) =>
    `<p><b>${label}</b>: ${names.length ? names.map(frappe.utils.escape_html).join(", ") : __("None")}</p>`;

  return `
    ${list(__("Leads to anonymize"), preview.leads)}
    ${list(__("Deals to anonymize"), preview.deals)}
    ${list(__("Contacts to delete"), preview.contacts)}
    <p class="text-muted">${__('Records whose text will be replaced with "Content erased {0}":', [requestName])}</p>
    <table class="table table-bordered">${rows || `<tr><td>${__("None")}</td></tr>`}</table>
    <p class="text-muted">${__("Organizations, deal values, statuses and dates are not changed.")}</p>`;
}

function showPreview(frm) {
  return frm.call("get_preview").then(({ message }) => {
    frappe.msgprint({
      title: __("What will be erased"),
      message: previewHtml(message, frm.doc.name),
      wide: true,
    });
    return message;
  });
}

function approve(frm) {
  frm.call("get_preview").then(({ message }) => {
    const dialog = new frappe.ui.Dialog({
      title: __("Approve and erase {0}?", [
        frm.doc.subject_name || frm.doc.name,
      ]),
      size: "large",
      fields: [
        { fieldtype: "HTML", options: previewHtml(message, frm.doc.name) },
        {
          fieldtype: "Data",
          fieldname: "confirm",
          label: __("Type ERASE to confirm. This cannot be undone."),
          reqd: 1,
        },
      ],
      primary_action_label: __("Erase"),
      primary_action({ confirm }) {
        if (confirm !== "ERASE") {
          frappe.msgprint(__("Type ERASE to confirm."));
          return;
        }
        dialog.hide();
        frm.call({ method: "approve_and_erase", freeze: true }).then(() => {
          frappe.show_alert({
            message: __("Erasure completed"),
            indicator: "green",
          });
          frm.reload_doc();
        });
      },
    });
    dialog.get_primary_btn().addClass("btn-danger");
    dialog.show();
  });
}

function reject(frm) {
  frappe.prompt(
    {
      fieldtype: "Small Text",
      fieldname: "reason",
      label: __("Reason"),
      reqd: 1,
    },
    ({ reason }) => frm.call("reject", { reason }).then(() => frm.reload_doc()),
    __("Reject erasure request"),
    __("Reject"),
  );
}
