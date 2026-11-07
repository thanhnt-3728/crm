import { describe, it, expect } from 'vitest'
import { showsRecordNames } from '@/utils/erasurePreviewKinds'

describe('showsRecordNames', () => {
  it('shows only the count for the notices written about the request itself', () => {
    for (const kind of [
      'hold_notifications',
      'hold_notification_logs',
      'hold_emails',
    ]) {
      expect(showsRecordNames(kind)).toBe(false)
    }
  })

  it('keeps listing the records behind every other kind', () => {
    for (const kind of ['leads', 'contacts', 'communications', 'versions']) {
      expect(showsRecordNames(kind)).toBe(true)
    }
  })
})
