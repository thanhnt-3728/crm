<template>
  <template v-if="lines.length">
    <h3 class="mb-2 mt-6 font-medium text-ink-gray-8">{{ __('Outcome') }}</h3>
    <div v-for="[label, value] in lines" :key="label" class="text-p-sm">
      {{ label }}: {{ value }}
    </div>
    <div
      v-if="request.known_limitations"
      class="mt-2 whitespace-pre-line text-p-sm text-ink-gray-6"
    >
      {{ request.known_limitations }}
    </div>
  </template>
</template>

<script setup>
import { computed } from 'vue'
import { outcomeEntries } from '@/utils/erasure-matches'

const props = defineProps({ request: { type: Object, required: true } })
const lines = computed(() => outcomeEntries(props.request.outcome))
</script>
