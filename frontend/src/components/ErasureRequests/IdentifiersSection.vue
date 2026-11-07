<template>
  <section class="flex flex-col gap-3 rounded-lg border p-4">
    <div>
      <h3 class="text-lg-medium text-ink-gray-9">{{ __('Identifiers') }}</h3>
      <p class="text-p-sm text-ink-gray-6">
        {{
          __(
            'Emails and phone numbers that drive the email and call sweep and the do-not-contact list. Exclude a shared office line or inbox so colleagues are not affected.',
          )
        }}
      </p>
    </div>
    <p v-if="!request.identifiers?.length" class="text-p-sm text-ink-gray-5">
      {{ __('No identifiers yet') }}
    </p>
    <div v-else class="divide-y text-base">
      <div
        v-for="row in request.identifiers"
        :key="row.name"
        class="flex items-center gap-3 py-2"
        :class="row.excluded && 'opacity-60'"
      >
        <Badge :label="__(row.kind)" theme="gray" variant="subtle" />
        <div class="min-w-0 flex-1">
          <div class="truncate text-ink-gray-8">{{ row.value }}</div>
          <div class="text-p-sm text-ink-gray-5">
            {{
              row.source === 'Record'
                ? __('From a record')
                : __('Typed on the request')
            }}
            <template v-if="impactOf(row)">
              · {{ impactText(impactOf(row)) }}
            </template>
          </div>
        </div>
        <Switch
          :model-value="Boolean(row.excluded)"
          :label="__('Exclude')"
          :disabled="!request.can?.edit"
          @update:model-value="(value) => setExcluded(row, value)"
        />
      </div>
    </div>
  </section>
</template>

<script setup>
import { erasureCall, runAction } from '@/components/ErasureRequests/erasureApi'
import { Badge, Switch } from 'frappe-ui'
import { ref, watch } from 'vue'

const props = defineProps({
  request: { type: Object, required: true },
})
const emit = defineEmits(['updated'])

// Impact counts come from an endpoint that only works while the request can still be edited.
const impact = ref({})

watch(
  () => [props.request.modified, props.request.can?.edit],
  async ([, editable]) => {
    if (!editable) {
      impact.value = {}
      return
    }
    try {
      const rows = await erasureCall('requests.get_identifier_impact', {
        name: props.request.name,
      })
      impact.value = Object.fromEntries(rows.map((row) => [row.row, row]))
    } catch {
      impact.value = {} // counts are a help, not a requirement: the rows still show
    }
  },
  { immediate: true },
)

const impactOf = (row) => impact.value[row.name]

function impactText(row) {
  const parts = [__('{0} records', [row.records])]
  if (row.communications !== null && row.communications !== undefined) {
    parts.push(__('{0} emails', [row.communications]))
    parts.push(__('{0} calls', [row.call_logs]))
  }
  return parts.join(', ') + (row.capped ? ' ' + __('(at least)') : '')
}

async function setExcluded(row, excluded) {
  const result = await runAction('requests.set_identifier_excluded', {
    name: props.request.name,
    row: row.name,
    excluded,
  })
  if (result) emit('updated', result)
}
</script>
