// Where a notification leads. `route_name` and `reference_name` come from
// crm.api.notifications.get_notifications.
export function notificationRoute(notification) {
  const id = notification.reference_name
  let params = { leadId: id }
  if (notification.route_name === 'Deal') {
    params = { dealId: id }
  } else if (notification.route_name === 'Erasure Request') {
    params = { requestId: id }
  } else if (notification.route_name === 'Erasure Email') {
    params = { emailId: id }
  } else if (notification.route_name === 'Erasure Requests') {
    params = {}
  }
  return {
    name: notification.route_name,
    params,
    hash: notification.hash,
  }
}
