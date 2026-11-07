<template>
  <div class="flex flex-col gap-4 text-base">
    <section>
      <h4 class="mb-1 text-p-base-medium text-ink-red-4">
        {{ __('Will be removed') }}
      </h4>
      <p v-if="!preview.remove.length" class="text-p-sm text-ink-gray-5">
        {{ __('Nothing to remove') }}
      </p>
      <ul v-else class="flex flex-col gap-2">
        <li
          v-for="item in preview.remove"
          :key="item.kind"
          class="text-ink-gray-8"
        >
          <span class="font-medium">{{ item.label }}</span>
          <span class="text-ink-gray-5"> · {{ item.count }}</span>
          <div
            v-if="showsRecordNames(item.kind)"
            class="flex flex-wrap gap-x-3 text-p-sm"
          >
            <template v-for="link in item.links" :key="link.name">
              <RouterLink
                v-if="routeOf(link)"
                :to="routeOf(link)"
                class="text-ink-gray-6 hover:underline"
                target="_blank"
              >
                {{ link.label || link.name }}
              </RouterLink>
              <span v-else class="text-ink-gray-6">{{
                link.label || link.name
              }}</span>
            </template>
            <span v-if="item.count > item.links.length" class="text-ink-gray-5">
              {{ __('and {0} more', [item.count - item.links.length]) }}
            </span>
          </div>
        </li>
      </ul>
    </section>
    <section>
      <h4 class="mb-1 text-p-base-medium text-ink-gray-9">
        {{ __('Will be kept') }}
      </h4>
      <ul class="flex flex-col gap-1 text-ink-gray-7">
        <li v-for="item in preview.keep" :key="item.kind">
          {{ item.text
          }}<span v-if="item.count" class="text-ink-gray-5">
            · {{ item.count }}</span
          >
        </li>
      </ul>
    </section>
    <section>
      <h4 class="mb-1 text-p-base-medium text-ink-amber-5">
        {{ __('Needs attention') }}
      </h4>
      <p v-if="!attention" class="text-p-sm text-ink-gray-5">
        {{ __('Nothing needs attention') }}
      </p>
      <ul v-else class="flex flex-col gap-1 text-ink-gray-7">
        <li v-for="item in preview.open_checklist" :key="item.description">
          {{
            item.predicted
              ? __('The erasure will add a checklist item: {0}', [
                  item.description,
                ])
              : __('Open checklist item: {0}', [item.description])
          }}
        </li>
        <li
          v-for="gap in preview.field_gaps"
          :key="gap.doctype + gap.fieldname"
        >
          {{
            __(
              '{0}: field "{1}" is not on the personal fields list and will not be erased',
              [__(gap.doctype), gap.label || gap.fieldname],
            )
          }}
        </li>
        <li v-for="hit in outside" :key="hit.kind + hit.identifier">
          {{
            __(
              '{0} also matches {1} records outside the confirmed ones, which will not be erased ({2} records, {3} emails, {4} calls in all{5})',
              [
                hit.identifier,
                hit.outside_her_records,
                hit.records,
                hit.communications ?? 0,
                hit.call_logs ?? 0,
                hit.capped ? ', ' + __('at least') : '',
              ],
            )
          }}
        </li>
        <li v-for="item in preview.needs_attention" :key="item.kind">
          {{ item.text
          }}<span v-if="item.count" class="text-ink-gray-5">
            · {{ item.count }}</span
          >
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup>
import { recordRoute } from '@/utils/erasureRequestDisplay'
import { showsRecordNames } from '@/utils/erasurePreviewKinds'
import { computed } from 'vue'

const props = defineProps({
  preview: { type: Object, required: true },
})

const routeOf = (link) => recordRoute(link.doctype, link.name)
const outside = computed(() =>
  props.preview.identifier_hits.filter((hit) => hit.outside_her_records > 0),
)
const attention = computed(
  () =>
    props.preview.open_checklist.length +
    props.preview.field_gaps.length +
    outside.value.length +
    props.preview.needs_attention.length,
)
</script>
