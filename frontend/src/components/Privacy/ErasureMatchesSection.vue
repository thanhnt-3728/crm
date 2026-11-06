<template>
  <div class="flex flex-col gap-6">
    <section>
      <div class="mb-1 text-lg-medium text-ink-gray-9">
        {{ __('Identifiers') }}
      </div>
      <div class="mb-2 text-sm text-ink-gray-5">
        {{
          __(
            'Emails and phones used to find the requester. Exclude one that others share, such as an office line.',
          )
        }}
      </div>
      <div v-if="!identifiers.length" class="text-base text-ink-gray-5">
        {{ __('No identifiers.') }}
      </div>
      <div
        v-for="row in identifiers"
        :key="row.kind + row.value"
        class="flex items-center gap-3 border-b py-2 text-base text-ink-gray-8"
      >
        <Badge :label="__(row.kind)" theme="gray" />
        <span class="min-w-0 flex-1 truncate">{{ row.value }}</span>
        <span class="whitespace-nowrap text-sm text-ink-gray-5">
          {{ __('{0} matches', [row.match_count || 0]) }}
        </span>
        <FormControl
          type="checkbox"
          :label="__('Exclude')"
          :modelValue="Boolean(row.excluded)"
          :disabled="!editable || saving"
          @change="(e) => toggleIdentifier(row, e.target.checked)"
        />
      </div>
    </section>

    <section>
      <div class="mb-1 text-lg-medium text-ink-gray-9">
        {{ __('Matched records') }}
      </div>
      <div class="mb-2 text-sm text-ink-gray-5">
        {{ __('Only confirmed records are erased.') }}
      </div>
      <div v-if="!matches.length" class="text-base text-ink-gray-5">
        {{ __('No matched records.') }}
      </div>
      <div
        v-for="row in matches"
        :key="row.reference_doctype + row.reference_name"
        class="flex items-center gap-3 border-b py-2 text-base text-ink-gray-8"
      >
        <span class="w-20 shrink-0 text-sm text-ink-gray-5">
          {{ doctypeLabel(row.reference_doctype) }}
        </span>
        <router-link
          v-if="recordRoute(row.reference_doctype, row.reference_name)"
          :to="recordRoute(row.reference_doctype, row.reference_name)"
          target="_blank"
          class="min-w-0 flex-1 truncate hover:underline"
        >
          {{ row.reference_name }}
        </router-link>
        <span v-else class="min-w-0 flex-1 truncate">
          {{ row.reference_name }}
        </span>
        <Badge v-if="row.source" :label="__(row.source)" theme="gray" />
        <Badge
          v-if="row.removed_from_open_deal"
          :label="__('Removed from open deal')"
          theme="orange"
        />
        <FormControl
          type="checkbox"
          :label="__('Confirmed')"
          :modelValue="Boolean(row.confirmed)"
          :disabled="!editable || saving"
          @change="(e) => toggleMatch(row, e.target.checked)"
        />
      </div>
    </section>
    <ErrorMessage :message="error" />
  </div>
</template>

<script setup>
import { errorText, recordRoute } from '@/utils/erasureRequest'
import { call } from 'frappe-ui'
import { computed, ref } from 'vue'

const props = defineProps({
  // the request, as the page loaded it
  request: { type: Object, required: true },
  // the logger while Logged, Compliance until approval
  editable: { type: Boolean, default: false },
})

// `refresh` fires after every change, so the page shows the recounted matches.
const emit = defineEmits(['refresh'])

const saving = ref(false)
const error = ref('')

const identifiers = computed(() => props.request.identifiers || [])
const matches = computed(() => props.request.matches || [])

const doctypeNames = {
  'CRM Lead': __('Lead'),
  'CRM Deal': __('Deal'),
  Contact: __('Contact'),
}
const doctypeLabel = (doctype) => doctypeNames[doctype] || doctype

// The server replaces both lists, so each change sends the whole of them.
async function save(nextIdentifiers, nextMatches) {
  saving.value = true
  error.value = ''
  try {
    await call('crm.api.erasure.update_matches', {
      name: props.request.name,
      identifiers: nextIdentifiers.map(({ kind, value, excluded }) => ({
        kind,
        value,
        excluded: excluded ? 1 : 0,
      })),
      matches: nextMatches.map(
        ({ reference_doctype, reference_name, confirmed }) => ({
          reference_doctype,
          reference_name,
          confirmed: confirmed ? 1 : 0,
        }),
      ),
    })
  } catch (e) {
    error.value = errorText(e)
  } finally {
    saving.value = false
    emit('refresh')
  }
}

function toggleIdentifier(row, excluded) {
  save(
    identifiers.value.map((item) =>
      item === row ? { ...item, excluded } : item,
    ),
    matches.value,
  )
}

function toggleMatch(row, confirmed) {
  save(
    identifiers.value,
    matches.value.map((item) => (item === row ? { ...item, confirmed } : item)),
  )
}
</script>
