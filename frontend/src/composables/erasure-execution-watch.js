import { dayjsLocal } from 'frappe-ui'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { executionStalled, shouldPoll } from '@/utils/erasure-actions'

const POLL_MS = 5000

// While an Approved request runs in the background, reload it every few seconds.
// Polling stops on an error or once the job is overdue (it died without a trace).
// `onStatusChange` runs when the status moves (Approved to Executed rewrites the matches).
export function useExecutionWatch(doc, reload, onStatusChange) {
  const now = ref(Date.now())
  const stalled = computed(() =>
    executionStalled({
      status: doc.value.status,
      approvedAt: doc.value.approved_on
        ? dayjsLocal(doc.value.approved_on).valueOf()
        : null,
      now: now.value,
    }),
  )

  let timer = null
  watch(
    () => [doc.value.status, doc.value.last_error, stalled.value],
    ([status, lastError, isStalled], previous) => {
      clearInterval(timer)
      timer = shouldPoll(status, lastError, isStalled)
        ? setInterval(() => {
            now.value = Date.now()
            reload()
          }, POLL_MS)
        : null
      if (previous?.[0] && previous[0] !== status) onStatusChange()
    },
    { immediate: true },
  )
  onBeforeUnmount(() => clearInterval(timer))
  return { stalled }
}
