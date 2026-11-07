import { call, toast } from 'frappe-ui'
import { errorText } from '@/utils/erasureRequestDisplay'

export const CHANNELS = ['Email', 'Phone', 'Web form', 'Mail', 'Other']

// 'review.approve_request' -> crm.api.erasure_review.approve_request
export function erasureCall(path, params = {}) {
  const [module, method] = path.split('.')
  return call(`crm.api.erasure_${module}.${method}`, params)
}

// A failure toasts the server's message and resolves null, so no call fails
// quietly and callers only branch on a result.
export async function runAction(path, params) {
  try {
    return await erasureCall(path, params)
  } catch (error) {
    toast.error(errorText(error))
    return null
  }
}
