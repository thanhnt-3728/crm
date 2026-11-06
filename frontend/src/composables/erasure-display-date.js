import { dayjs } from 'frappe-ui'
import { getFormat } from '@/utils'

// Site date format for a 'YYYY-MM-DD' value; parsed without a time zone so the day never shifts.
export function displayDate(date) {
  if (!date) return ''
  const day = String(date).slice(0, 10)
  return dayjs(day).format(getFormat(day, '', true, false, false))
}
