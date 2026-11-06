<template>
  <div
    v-if="items?.length"
    class="rounded bg-surface-amber-2 p-2 text-p-sm text-ink-amber-3"
  >
    <div v-for="item in items" :key="`${item.kind}-${item.position}`">
      {{
        __('{0} {1} was not found on her records. Check it belongs to her.', [
          __(item.kind),
          item.position,
        ])
      }}
    </div>
  </div>
</template>

<script setup>
// Kind and position only (e.g. "Email 2"), never the identifier itself.
defineProps({ items: { type: Array, default: () => [] } })
</script>
