// A user whose top CRM role is Compliance holds none of the sales roles (the
// server ranks Compliance below them), so they may not read FCRM Settings, the
// availability statuses or any other sales doctype. Anything the app requests on
// load for every user has to skip those reads, or each one is a 403 and a console
// error. While the role is not known yet the answer stays "yes", as it always was.
export function canReadSalesData(role) {
  return role !== 'Compliance'
}

// The layout renders before the first navigation has waited for the users list,
// so at that moment the role is still unknown. Decide only once `usersReady`
// (the promise of the users resource) has settled; a failed users request leaves
// the role unknown, which allows the call, as before.
export async function runIfSalesUser(usersReady, getRole, action) {
  try {
    await usersReady
  } catch {
    // role stays unknown
  }
  if (canReadSalesData(getRole())) return action()
}
