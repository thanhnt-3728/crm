# CRM Scripting — Stable Contracts

> **This file**: Stable, user-facing API contracts only. No future plans. No implementation history.  
> **Roadmap**: [PLAN.md](./PLAN.md)  
> **Completed phases**: [ARCHIVE.md](./ARCHIVE.md)  
> **Full scripting guide**: [feats/form-scripting/guide.md](./feats/form-scripting/guide.md)  
> **formDialog full reference**: [feats/form-scripting/form-dialog.md](./feats/form-scripting/form-dialog.md)

---

## Table of Contents

1. [Form Script Class Contract](#form-script-class-contract)
2. [Lifecycle Hooks](#lifecycle-hooks)
3. [Field Change Hooks](#field-change-hooks)
4. [setFieldProperty API](#setfieldproperty-api)
5. [Supported Field Properties](#supported-field-properties)
6. [Override Priority](#override-priority)
7. [formDialog API](#formdialog-api)
8. [Available Helpers](#available-helpers)
9. [Testing](#testing)
10. [Personal Data Erasure](#personal-data-erasure)

---

## Form Script Class Contract

Class name = DocType name with spaces removed:

| DocType | Class name |
|---|---|
| `CRM Lead` | `CRMLead` |
| `CRM Deal` | `CRMDeal` |
| `Contact` | `Contact` |
| `CRM Organization` | `CRMOrganization` |

```js
class CRMLead {
  // hooks go here
}
```

`this.doc` — live proxy to the document. Read/write fields directly. No `.value`.  
`this.doc.trigger('methodName')` — the correct way to call methods on your own class.

---

## Lifecycle Hooks

| Hook | Aliases | When it fires |
|---|---|---|
| `onLoad` | `on_load` | Once, when document first loads from server |
| `onRender` | `on_render`, `refresh` | Every time the page renders (first visit + re-visits) |
| `onValidate` | `on_validate`, `validate` | Before every save — throw to block |
| `onSave` | `on_save` | After a successful save |
| `onError` | `on_error` | When a save fails |
| `onBeforeCreate` | `on_before_create` | Before a new document is created via modal |
| `onCreateLead` | `on_create_lead` | CRM Lead only — lead creation flow |
| `convertToDeal` | `convert_to_deal` | CRM Lead only — lead to deal conversion |

All hooks are optional. All hooks can be `async`.

---

## Field Change Hooks

Define a method named **exactly the same as the fieldname**:

```js
class CRMLead {
  status() { /* fires when status field changes */ }
  annual_revenue() { /* fires when annual_revenue changes */ }
}
```

Inside a field hook:
- `this.value` — the new value just set
- `this.oldValue` — the previous value
- `this.currentRowIdx` — the row index if the change was inside a child table

**Row add/remove hooks:**
- `[parentfield]_add` — fires after a row is added. `this.value` = new row object
- `[parentfield]_remove` — fires after row(s) are deleted. `this.selectedRows` = removed names

---

## setFieldProperty API

### `this.setFieldProperty(target, property, value [, rowName])`

```js
// Field
this.setFieldProperty('annual_revenue', 'hidden', true)
this.setFieldProperty('status', 'options', 'New\nOpen\nClosed')

// Section or tab (by name from layout)
this.setFieldProperty('financial_section', 'hidden', true)
this.setFieldProperty('advanced_tab', 'hidden', true)

// Child table column (dot notation)
this.setFieldProperty('products.discount', 'hidden', true)

// Specific row in child table (4th param: row.name)
this.setFieldProperty('products.rate', 'read_only', true, row.name)
```

### `this.setFieldProperties(target, properties [, rowName])`

```js
this.setFieldProperties('annual_revenue', {
  read_only: true,
  label: 'Revenue (USD)',
  description: 'Auto-calculated',
})
```

### `this.removeFieldProperty(target, property [, rowName])`

```js
this.removeFieldProperty('annual_revenue', 'hidden')
this.removeFieldProperty('products.rate', 'read_only', row.name)
```

### `this.getField(fieldname)`

Returns effective field definition (raw meta merged with current script overrides). Not reactive — call again after changes.

```js
const field = this.getField('status')
console.log(field.options, field.read_only, field.hidden)
```

---

## Supported Field Properties

### Field

| Property | Type | Effect |
|---|---|---|
| `hidden` | `boolean` | Show/hide the field |
| `read_only` | `boolean` | Make non-editable |
| `reqd` | `boolean` | Make mandatory (asterisk + validation) |
| `label` | `string` | Field label |
| `placeholder` | `string` | Input placeholder |
| `description` | `string` | Help text below the field |
| `options` | `string` | Select choices (newline-separated) or Link doctype |
| `link_filters` | `object` | Filter object for Link autocomplete |
| `precision` | `string` | Decimal precision for Float/Currency/Percent |
| `button_color` | `string` | `"Default"`, `"Primary"`, `"Info"`, `"Success"`, `"Warning"`, `"Danger"` |

**Select `options` format** — always a newline-separated string:
```js
this.setFieldProperty('status', 'options', 'New\nIn Progress\nClosed')
```

**`link_filters` format** — plain object:
```js
this.setFieldProperty('lead_owner', 'link_filters', { enabled: 1 })
```

### Section

| Property | Type | Effect |
|---|---|---|
| `hidden` | `boolean` | Show/hide entire section |
| `label` | `string` | Section heading |
| `collapsible` | `boolean` | Make collapsible |
| `opened` | `boolean` | Default expanded state |
| `hideLabel` | `boolean` | Hide the section label |
| `hideBorder` | `boolean` | Remove top border |

### Tab

| Property | Type | Effect |
|---|---|---|
| `hidden` | `boolean` | Show/hide the entire tab |
| `label` | `string` | Tab heading |

---

## Override Priority

```
Final value =
  1. Script per-row override  (products.qty:row_name)    ← highest
  2. Script column override   (products.qty)
  3. Script field override    (fieldname)
  4. depends_on expression    (read_only_depends_on, etc.)
  5. Server meta default                                  ← lowest
```

**Hidden fields are always skipped in mandatory validation.** A field hidden via script override is never checked for `reqd`, even if `reqd: 1` in the DocType.

---

## formDialog API

Opens a dialog with a full FieldLayout. Returns a `Promise<object|null>`.

```js
formDialog(options)
```

### Three patterns (all composable)

```js
// 1. Promise — sequential, await the result
const data = await formDialog({ title: 'Step 1', fields: [...] })
if (!data) return  // cancelled

// 2. onSubmit callback — fire-and-forget, code after runs immediately
formDialog({
  title: 'Mark as Lost',
  fields: [...],
  submitLabel: 'Mark as Lost',
  cancelLabel: 'Cancel',
  onSubmit(data) { ... },
  onCancel() { ... },
})

// 3. Custom actions — full control
formDialog({
  title: 'Review',
  fields: [...],
  actions: [
    { label: 'Approve', variant: 'solid', onClick({ data, close, validate }) { close(data) } },
    { label: 'Cancel', onClick({ close }) { close(null) } },
  ],
})
```

### Options

| Option | Type | Description |
|---|---|---|
| `title` | `string` | Dialog title |
| `fields` | `Array` | Flat field definitions — auto-wrapped in single section |
| `tabs` | `Array` | Full layout: `tabs > sections > columns > fields` |
| `doctype` | `string` | Fetch Quick Entry layout for this doctype |
| `fieldnames` | `Array<string>` | With `doctype` — pick only these fields from doctype meta |
| `defaults` | `object` | Pre-fill field values |
| `required` | `Array<string>` | Force mandatory: shows asterisk + validates |
| `size` | `string` | Dialog size: `'sm'`, `'md'`, `'lg'`, `'xl'`, `'2xl'`. Default: `'xl'` |
| `actions` | `Array` | Custom buttons — overrides default Submit and `onSubmit` |
| `onSubmit` | `Function` | Called with `data` on submit. Throw to stay open |
| `onCancel` | `Function` | Called on cancel/close/overlay/escape |
| `submitLabel` | `string` | Default Submit button label. Default: `'Submit'` |
| `cancelLabel` | `string` | If provided, shows a Cancel button with this label |

### Behavior matrix

| `actions` | `onSubmit` | Behavior |
|---|---|---|
| ✗ | ✗ | Submit button → validates → closes → Promise resolves with data |
| ✗ | ✓ | Submit button → validates → `onSubmit(data)` → closes → Promise resolves |
| ✓ | (ignored) | Custom buttons only. Each calls `close(result)` |

> Full reference with layout modes, column layouts, and examples: [feats/form-scripting/form-dialog.md](./feats/form-scripting/form-dialog.md)

---

## Available Helpers

All helpers are available as bare names everywhere in your script — no imports needed.

| Helper | Description |
|---|---|
| `call(method, params)` | Frappe backend RPC — returns a `Promise` |
| `toast.success(msg)` | Green toast notification |
| `toast.error(msg)` | Red toast notification |
| `toast.info(msg)` | Info toast notification |
| `createDialog(options)` | Simple frappe-ui confirm/message dialog (fire-and-forget) |
| `formDialog(options)` | Form dialog with FieldLayout — returns a Promise. See [form-dialog.md](./feats/form-scripting/form-dialog.md) |
| `router` | Vue Router — `router.replace()`, `router.push()`, `router.currentRoute` |
| `router.previousRoute` | Route navigated from — compare `.path` (not `.fullPath`) |
| `socket` | Socket.io instance for realtime events |
| `throwError(message)` | `toast.error` + `throw` in one call — stops execution |
| `crm.makePhoneCall(number)` | Initiate a phone call via CRM call integration |
| `crm.openSettings(page)` | Open the CRM settings panel to a specific page |

---

## Testing

**Runner**: Vitest · **Environment**: happy-dom  
**Location**: `frontend/tests/`

```bash
cd frontend
yarn test          # watch mode
yarn test:run      # single run (CI)
```

**Current state**: 6 test files · 118 tests · ~250ms

### Test files

| File | What it tests |
|---|---|
| `processField.test.js` | Field clone, Select/Link transforms, perm + script overrides |
| `fieldPropertyOverrides.test.js` | setFieldProperty / remove / batch / dot notation / per-row |
| `checkMandatory.test.js` | findMissingMandatory with script override scenarios |
| `scriptHelpers.test.js` | getClassNames, createDocProxy |
| `parseLinkFilters.test.js` | Safe JSON/object parsing for link_filters |
| `renderFieldLayoutDialog.test.js` | Promise behavior, options passthrough, onSubmit/onCancel, concurrent dialogs |

### Rules for adding tests

- Functions under test must be **pure** and **importable without side effects**
- If a function needs extraction from a Vue component, extract to `src/utils/` first
- Use `@/` alias (resolves to `src/`), standard `describe`/`it`/`expect` (vitest globals)

```js
import { processField } from '@/utils/fieldTransforms'

describe('processField', () => {
  it('clones the field', () => {
    const raw = { fieldname: 'x', fieldtype: 'Data' }
    expect(processField(raw)).not.toBe(raw)
  })
})
```

> See `tests/setup.js` for available globals (`__`, `window.sysdefaults`)

---

## Personal Data Erasure

> Contract of the CCPA erasure feature. User steps: [feats/personal-data-erasure/guide.md](./feats/personal-data-erasure/guide.md). Why it is built this way: [ARCHIVE.md](./ARCHIVE.md#ccpa-personal-data-erasure).

### Registry entry

The registry is the single list of where a person's data lives. Its table is **not** copied here: read [`crm/erasure/registry.py`](../crm/erasure/registry.py) (entries in `registry_subject_entries.py` and `registry_activity_entries.py`), the shapes in [`crm/erasure/registry_model.py`](../crm/erasure/registry_model.py), and the generated manual copy [docs/ccpa-manual-erasure-runbook.md](../docs/ccpa-manual-erasure-runbook.md).

An `Entry` has `doctype`, `kind` (`person`, `activity`, `file`, `hidden`), `found_by` (text for the runbook), `finders`, `action` and per-field treatments. Adding a data source means adding an entry.

| Action | Effect |
|---|---|
| `scrub` | anonymize the listed fields in place, keep the row |
| `replace_content` | keep the row, overwrite its content with the content marker |
| `delete_permanently` | delete with no Deleted Document copy (files: after commit) |
| `purge` | delete a hidden copy outright |
| `filter_entries` | Version rows: drop only the entries that carry her data |
| `unlink` | shared record (an Address of several people): drop her link row only |
| `rewrite_comments` | `_comments` column: keep entries that hold only a name |

Field treatments: `clear`, `marker`, `name_marker`, `remove_address`, `clear_if_hers`, `marker_if_hers`, `delete_rows`, `drop_her_links`.

**Markers**: `content_marker(REQ)` is `Content erased <REQ-no>`; `name_marker(REQ)` is `Erased <REQ-no>`. Activity rows (emails, comments, calls, notes, tasks, WhatsApp) are kept so counts and dashboards do not move; only their content changes.

Residual limits are listed in `KNOWN_LIMITATIONS` in `registry.py`. Each Executed request stores them (`known_limitations`) and its page shows them.

### Request doctype `CRM Erasure Request`

Named `CRM-ERQ-.YYYY.-<n>`. Child tables: `CRM Erasure Identifier` (kind Email or Phone, value, normalized) and `CRM Erasure Match` (`ref_doctype`, `ref_name`, reason, action, excluded, new_since_logging). Deadlines (`erasure_deadlines.py`): `ack_due` is 10 business days after `received_on`, `response_due` is 45 calendar days. Holidays come from `FCRM Settings.erasure_holiday_list` (Link to `CRM Holiday List`); empty means weekends only.

Role `Privacy Officer` is additive (created by `crm/install.py` and patch `crm.patches.v1_0.add_privacy_officer_role`); holders also need a CRM role. DocType permissions: System Manager full; Sales User create, and read/write own; Sales Manager read (cannot log); Privacy Officer read and write. The `matches` table is permlevel 1: over REST only Privacy Officer and System Manager see match rows, requesters use `get_preview`. After logging, `identifiers`, `source_doctype` and `source_docname` cannot be changed by a form or REST save; `refresh_matches` and `submit_for_approval` re-check that at least one identifier is on the source ("None of the identifiers of <REQ> is on <doctype> <name>"). Only a Draft request can be deleted (audit record; its Deleted Document copy holds no identifiers). Due dates are computed on insert and when `received_on` changes only.

### States (`erasure_states.py`, `TRANSITIONS`)

| From | To | Actor |
|---|---|---|
| Draft | Pending Approval, or On Hold | requester |
| Pending Approval | On Hold (and back) | system (hold rule) |
| Pending Approval | Approved | decider |
| Approved | Executed | system (execution job) |
| Executed | Closed | any Privacy Officer |
| Draft, Pending Approval, On Hold | Rejected | decider |

Decider: a Privacy Officer who is neither `requested_by` nor `owner` (two-person rule, checked against stored values and `frappe.session.user`). Open states, which block delete and rename: Draft, Pending Approval, On Hold, Approved. Closed and Rejected are terminal.

**Hold rule** (`erasure_hold.py`): while a request is Pending Approval or On Hold and her Lead, Deal or Contact is tied to a deal whose status type is not Won or Lost, the request is On Hold (deadlines keep running). It re-evaluates on Deal update and delete, and `approve` re-checks it before and after re-planning matches. If an open deal is found it moves the request to On Hold, commits, and throws the hold error.

### API

Endpoints live in `crm/api/erasure.py` and `crm/erasure/approval.py`. All are POST-only and whitelisted as `crm.api.erasure.<name>`. Match keys are `"<ref_doctype>::<ref_name>"`. Previews return `{name, status, hold_reason, ack_due, response_due, groups[{doctype, count, excluded, unreadable, rows[...]}], hidden, identifiers_not_on_subject[{kind, position}]}` (also from `get_preview` and `get_approval_preview`); identifiers are never echoed, only their position.

| Endpoint | Who may call it |
|---|---|
| `log_request(source_doctype, source_docname, subject_name, received_on, emails, phones)` | user with create on the doctype who can read the source; one identifier must be on the source |
| `refresh_matches(name)` | Draft: its requester; Pending Approval or On Hold: a decider; otherwise refused |
| `set_exclusions(name, excluded)` | requester, Draft only |
| `submit_for_approval(name)` | requester (Draft to Pending Approval, or On Hold) |
| `get_preview(name)` | requester or a Privacy Officer |
| `get_approval_preview(name)` | decider, Pending Approval or On Hold; adds `preview_hash` |
| `approve(name, confirm_name, excluded, preview_hash)` | decider; `confirm_name` must equal the request number; a stale hash raises `ErasurePreviewStale` |
| `reject(name, reason)` | decider; reason required; applies the same retention as Close in the same transaction |
| `close(name)` | any Privacy Officer; Executed only; applies retention |
| `retry_execution(name)` | any Privacy Officer; Approved only; queues the job again |

The acknowledgement date is saved with `frappe.client.set_value` on `acknowledged_on` (editable after Draft).

### Execution

`approve` queues `crm.erasure.jobs.execute_request` (long queue, one job per request, after commit). One transaction does the database work in registry order, runs a residual check and marks the request Executed with an `outcome`; files are deleted after the commit and global search is re-indexed. A failure rolls back, records `last_error` (exception class and doctype, never a value) and leaves the request Approved so `retry_execution` can run it again.

### Guards (`erasure_guards.py`, wired in `crm/hooks.py`)

- Lead, Deal and Contact: `on_trash` refuses delete while an open request points at the record; `before_rename` refuses rename or merge (only the execution job may rename her Contact and Address); `after_rename` rewrites references of decided requests.
- Deal `on_update` and `on_trash` feed the hold rule.

`outcome` carries `pending_files` (sha256 of site-relative paths; empty when done). To retry disk deletion, also on Closed requests: `bench --site <site> execute crm.erasure.post_commit.finish_files --kwargs "{'name': '<REQ>'}"`.

### Retention seam

`crm/erasure/retention.py` `apply_retention(request)` runs at Close and at Reject, and is the one place that decides what a request keeps. Current behavior: masked emails and phones, request number and dates kept; the subject name is replaced by the name marker.

### Tests

```bash
bench --site test_site run-tests --app crm --module crm.erasure.test_end_to_end
# all backend modules: crm/erasure/test_*.py and crm/fcrm/doctype/crm_erasure_request/test_*.py
cd frontend && yarn test:run   # includes erasure-actions, erasure-deadlines, erasure-display-date, erasure-matches
```
