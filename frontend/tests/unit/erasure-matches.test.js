import {
  groupMatches,
  toggleExclusion,
  isConfirmationValid,
  prefillIdentifiers,
  serverMessage,
  isStalePreviewError,
  outcomeEntries,
  sortNewFirst,
  countNewRows,
  canConfirmApproval,
  sameKeys,
  isToggleable,
  excludedKeys,
} from '@/utils/erasure-matches'

describe('server errors', () => {
  it('prefers the first server message, then the error message, then the fallback', () => {
    expect(serverMessage({ messages: ['A', 'B'], message: 'M' }, 'F')).toBe('A')
    expect(serverMessage(new Error('M'), 'F')).toBe('M')
    expect(serverMessage({}, 'F')).toBe('F')
    expect(serverMessage(null, 'F')).toBe('F')
  })

  it('recognises a stale preview by exception type, and only that', () => {
    expect(isStalePreviewError({ exc_type: 'ErasurePreviewStale' })).toBe(true)
    expect(isStalePreviewError({ exc_type: 'PermissionError' })).toBe(false)
    expect(
      isStalePreviewError({ messages: ['The matches changed, reload'] }),
    ).toBe(false)
    expect(isStalePreviewError(null)).toBe(false)
  })
})

describe('groupMatches', () => {
  const rows = [
    { ref_doctype: 'CRM Lead', ref_name: 'L1', excluded: 0 },
    { ref_doctype: 'Communication', ref_name: 'C1', excluded: 1 },
    { ref_doctype: 'CRM Lead', ref_name: 'L2', excluded: 0 },
  ]

  it('groups by doctype in first-seen order with counts and excluded counts', () => {
    const groups = groupMatches(rows)
    expect(groups.map((g) => g.doctype)).toEqual(['CRM Lead', 'Communication'])
    expect(groups[0].count).toBe(2)
    expect(groups[0].rows.map((r) => r.ref_name)).toEqual(['L1', 'L2'])
    expect(groups[1]).toMatchObject({ count: 1, excluded: 1 })
  })

  it('gives each row a key "<doctype>::<name>"', () => {
    expect(groupMatches(rows)[0].rows[0].key).toBe('CRM Lead::L1')
  })

  it('returns an empty list for no rows', () => {
    expect(groupMatches([])).toEqual([])
    expect(groupMatches(undefined)).toEqual([])
  })
})

describe('toggleExclusion', () => {
  it('adds a missing key and removes a present one without mutating', () => {
    const start = new Set(['a'])
    const added = toggleExclusion(start, 'b')
    expect([...added].sort()).toEqual(['a', 'b'])
    expect([...start]).toEqual(['a'])
    expect([...toggleExclusion(added, 'b')]).toEqual(['a'])
  })

  it('toggling twice returns to included', () => {
    const twice = toggleExclusion(toggleExclusion(new Set(), 'k'), 'k')
    expect(twice.has('k')).toBe(false)
  })
})

describe('isConfirmationValid', () => {
  const name = 'CRM-ERQ-2026-00001'

  it('accepts the exact name, trimming only the ends', () => {
    expect(isConfirmationValid(name, name)).toBe(true)
    expect(isConfirmationValid(`  ${name}\n`, name)).toBe(true)
  })

  it.each([
    ['lower case', 'crm-erq-2026-00001'],
    ['partial', 'CRM-ERQ-2026-0000'],
    ['extra characters', `${name}1`],
    ['inner whitespace', 'CRM-ERQ-2026- 00001'],
    ['empty', ''],
    ['blank', '   '],
  ])('rejects %s', (_label, typed) => {
    expect(isConfirmationValid(typed, name)).toBe(false)
  })

  it('rejects when there is no request name or no input', () => {
    expect(isConfirmationValid('', '')).toBe(false)
    expect(isConfirmationValid(undefined, name)).toBe(false)
    expect(isConfirmationValid(name, undefined)).toBe(false)
  })
})

describe('prefillIdentifiers', () => {
  it('reads a lead: name, email, mobile and phone', () => {
    const doc = {
      lead_name: 'Marisol Vega',
      email: 'marisol@example.net',
      mobile_no: '+1 555 0100',
      phone: '+1 555 0200',
    }
    expect(prefillIdentifiers(doc, 'CRM Lead')).toEqual({
      subject_name: 'Marisol Vega',
      emails: ['marisol@example.net'],
      phones: ['+1 555 0100', '+1 555 0200'],
    })
  })

  it('builds the name from first and last name when lead_name is missing', () => {
    const out = prefillIdentifiers(
      { first_name: 'Ana', last_name: 'Ruiz' },
      'CRM Lead',
    )
    expect(out.subject_name).toBe('Ana Ruiz')
  })

  it('skips empty phones and does not repeat a phone', () => {
    const out = prefillIdentifiers(
      { lead_name: 'A', mobile_no: '555', phone: '555', email: '' },
      'CRM Lead',
    )
    expect(out.phones).toEqual(['555'])
    expect(out.emails).toEqual([])
    const blank = prefillIdentifiers(
      { lead_name: 'A', mobile_no: ' ', phone: null },
      'CRM Lead',
    )
    expect(blank.phones).toEqual([])
  })

  it('reads a deal: own fields plus the contacts table, de-duplicated', () => {
    const doc = {
      lead_name: 'Marisol Vega',
      email: 'm@example.net',
      mobile_no: '555',
      contacts: [
        {
          full_name: 'Marisol Vega',
          email: 'M@example.net',
          mobile_no: '555',
          phone: '777',
        },
        { full_name: 'Other', email: 'o@example.net' },
      ],
    }
    const out = prefillIdentifiers(doc, 'CRM Deal')
    expect(out.subject_name).toBe('Marisol Vega')
    expect(out.emails).toEqual(['m@example.net', 'o@example.net'])
    expect(out.phones).toEqual(['555', '777'])
  })

  it('reads a contact: full name, email_id, child tables', () => {
    const doc = {
      full_name: 'Marisol Vega',
      email_id: 'm@example.net',
      mobile_no: '555',
      email_ids: [
        { email_id: 'm@example.net' },
        { email_id: 'alt@example.net' },
      ],
      phone_nos: [{ phone: '555' }, { phone: '888' }],
    }
    expect(prefillIdentifiers(doc, 'Contact')).toEqual({
      subject_name: 'Marisol Vega',
      emails: ['m@example.net', 'alt@example.net'],
      phones: ['555', '888'],
    })
  })

  it('returns empty values for a missing doc', () => {
    expect(prefillIdentifiers(null, 'CRM Lead')).toEqual({
      subject_name: '',
      emails: [],
      phones: [],
    })
  })
})

describe('outcomeEntries', () => {
  it('flattens nested counts and parses a JSON string', () => {
    const json = JSON.stringify({
      'CRM Lead': 1,
      docs: { Communication: 4 },
      files_deleted: 2,
    })
    expect(outcomeEntries(json)).toEqual([
      ['CRM Lead', 1],
      ['docs / Communication', 4],
      ['files_deleted', 2],
    ])
  })

  it('returns no lines for empty, invalid or missing outcome', () => {
    expect(outcomeEntries('')).toEqual([])
    expect(outcomeEntries('{not json')).toEqual([])
    expect(outcomeEntries(null)).toEqual([])
  })
})

describe('new rows at approval', () => {
  const groups = [
    {
      doctype: 'Communication',
      unreadable: 0,
      rows: [
        { id: 'C1', new_since_logging: 0 },
        { id: 'C2', new_since_logging: 1 },
        { id: 'C3', new_since_logging: 0 },
        { id: 'C4', new_since_logging: 1 },
      ],
    },
    {
      doctype: 'CRM Lead',
      unreadable: 2,
      rows: [{ id: 'L1', new_since_logging: 0 }],
    },
  ]

  it('sorts new rows first, keeping order within each kind and the other fields', () => {
    const sorted = sortNewFirst(groups)
    expect(sorted[0].rows.map((r) => r.id)).toEqual(['C2', 'C4', 'C1', 'C3'])
    expect(sorted[1]).toEqual(groups[1])
    expect(groups[0].rows[0].id).toBe('C1')
  })

  it('counts new rows across groups', () => {
    expect(countNewRows(groups)).toBe(2)
    expect(countNewRows([])).toBe(0)
    expect(countNewRows(undefined)).toBe(0)
  })

  it('needs the exact number, and the review box when there are new rows', () => {
    const ok = {
      typed: 'CRM-ERQ-1',
      name: 'CRM-ERQ-1',
      newCount: 2,
      reviewed: true,
    }
    expect(canConfirmApproval(ok)).toBe(true)
    expect(canConfirmApproval({ ...ok, reviewed: false })).toBe(false)
    expect(canConfirmApproval({ ...ok, typed: 'crm-erq-1' })).toBe(false)
    expect(canConfirmApproval({ ...ok, newCount: 0, reviewed: false })).toBe(
      true,
    )
    expect(canConfirmApproval({ ...ok, newCount: 0, typed: '' })).toBe(false)
  })
})

describe('sameKeys', () => {
  it('compares sets by content, ignoring order', () => {
    expect(sameKeys(new Set(['a', 'b']), new Set(['b', 'a']))).toBe(true)
    expect(sameKeys(new Set(), new Set())).toBe(true)
  })

  it('detects an added, removed or swapped key', () => {
    expect(sameKeys(new Set(['a']), new Set(['a', 'b']))).toBe(false)
    expect(sameKeys(new Set(['a', 'b']), new Set(['a']))).toBe(false)
    expect(sameKeys(new Set(['a']), new Set(['b']))).toBe(false)
  })
})

describe('rows excluded with their parent', () => {
  const groups = [
    {
      doctype: 'ToDo',
      rows: [
        { key: 'ToDo::1', excluded: 1, reason: 'via_excluded' },
        { key: 'ToDo::2', excluded: 1, reason: 'email match' },
        { key: 'ToDo::3', excluded: 0, reason: 'email match' },
      ],
    },
  ]

  it('cannot toggle a row that is excluded only because its parent is', () => {
    expect(isToggleable({ reason: 'via_excluded' })).toBe(false)
    expect(isToggleable({ reason: 'email match' })).toBe(true)
    expect(isToggleable({})).toBe(true)
  })

  it('keeps only the rows the user excluded herself', () => {
    expect([...excludedKeys(groups)]).toEqual(['ToDo::2'])
    expect(excludedKeys(undefined).size).toBe(0)
  })
})
