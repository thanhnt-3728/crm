<template>
  <section class="flex flex-col gap-3 rounded-lg border p-4">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h3 class="text-lg-medium text-ink-gray-9">{{ __('Matches') }}</h3>
        <p class="text-p-sm text-ink-gray-6">
          {{
            __(
              'Only confirmed records are erased. Confirm the ones that are the person.',
            )
          }}
        </p>
      </div>
      <div class="flex gap-2">
        <Button
          v-if="request.can?.recheck_hold"
          :label="__('Re-check hold')"
          :loading="busy === 'recheck'"
          @click="recheck"
        />
        <Button
          v-if="request.can?.edit"
          :label="__('Find matches')"
          :loading="busy === 'find'"
          @click="findMatches"
        />
      </div>
    </div>
    <p v-if="!request.matches?.length" class="text-p-sm text-ink-gray-5">
      {{
        __(
          'No matches yet. Find matches to look for records that share an identifier.',
        )
      }}
    </p>
    <div v-else class="divide-y text-base">
      <div
        v-for="row in request.matches"
        :key="row.name"
        class="flex items-center gap-3 px-2 py-2"
        :class="isHeld(row) && 'rounded bg-surface-amber-2'"
      >
        <div class="min-w-0 flex-1">
          <RouterLink
            v-if="routeOf(row)"
            :to="routeOf(row)"
            class="truncate font-medium text-ink-gray-9 hover:underline"
          >
            {{ row.label || row.reference_name }}
          </RouterLink>
          <span v-else class="truncate font-medium text-ink-gray-9">{{
            row.label || row.reference_name
          }}</span>
          <div class="text-p-sm text-ink-gray-5">
            {{ __(row.reference_doctype) }} · {{ row.reason }}
            <template v-if="row.owner_name">
              · {{ __('Owner: {0}', [row.owner_name]) }}
            </template>
          </div>
        </div>
        <Badge
          v-if="row.is_source"
          :label="__('Started from')"
          theme="blue"
          variant="subtle"
        />
        <Badge
          v-else-if="isHeld(row)"
          :label="__('Holds the request')"
          theme="orange"
          variant="subtle"
        />
        <Badge v-else :label="__(row.relation)" theme="gray" variant="subtle" />
        <Switch
          :model-value="Boolean(row.confirmed)"
          :label="__('Confirmed')"
          :disabled="Boolean(row.is_source) || !request.can?.edit"
          @update:model-value="(value) => setConfirmed(row, value)"
        />
      </div>
    </div>
  </section>
</template>

<script setup>
import { runAction } from '@/components/ErasureRequests/erasureApi'
import { recordRoute } from '@/utils/erasureRequestDisplay'
import { Badge, Switch, toast } from 'frappe-ui'
import { ref } from 'vue'

const props = defineProps({
  request: { type: Object, required: true },
})
const emit = defineEmits(['updated'])

const busy = ref('')

const routeOf = (row) => recordRoute(row.reference_doctype, row.reference_name)
// `owner_name` comes from the server for the open deals that hold the request
const isHeld = (row) =>
  props.request.status === 'On Hold' &&
  (row.relation === 'Hold deal' || Boolean(row.owner_name))

async function act(kind, path, params, onDone) {
  busy.value = kind
  const result = await runAction(path, { name: props.request.name, ...params })
  busy.value = ''
  if (!result) return
  emit('updated', result)
  onDone?.(result)
}

const findMatches = () => act('find', 'requests.suggest_matches', {})

const recheck = () => act('recheck', 'requests.recheck_hold', {})

const setConfirmed = (row, confirmed) =>
  act(
    'confirm',
    'requests.set_match_confirmed',
    { row: row.name, confirmed },
    (result) => {
      const skipped = result.skipped_identifiers?.length
      if (skipped) {
        toast.warning(
          __(
            '{0} identifiers on this record were skipped because they are unusable',
            [skipped],
          ),
        )
      }
    },
  )
</script>
