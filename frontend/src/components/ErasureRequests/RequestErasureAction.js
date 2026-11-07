// The shared "Request erasure" dropdown item of the Lead, Deal and Contact headers.
export function requestErasureItem(onClick) {
  return { label: __('Request erasure'), icon: 'lucide-user-x', onClick }
}

// The contacts a deal lists, as the new-request dialog's contact choices.
export function contactChoices(contacts) {
  return (contacts || []).map((contact) => ({
    label: contact.full_name || contact.name,
    value: contact.name,
  }))
}
