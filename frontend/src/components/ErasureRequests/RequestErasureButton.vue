<template>
  <Dropdown
    :options="[requestErasureItem(() => (showDialog = true))]"
    align="end"
  >
    <Button icon="lucide-more-horizontal" :tooltip="__('More actions')" />
  </Dropdown>
  <NewErasureRequestDialog v-model="showDialog" :source="source" />
</template>

<script setup>
import NewErasureRequestDialog from '@/components/ErasureRequests/NewErasureRequestDialog.vue'
import {
  contactChoices,
  requestErasureItem,
} from '@/components/ErasureRequests/RequestErasureAction'
import { Dropdown } from 'frappe-ui'
import { computed, ref } from 'vue'

const props = defineProps({
  doctype: { type: String, required: true },
  name: { type: String, required: true },
  // a deal's contacts: the person is picked when there are several
  contacts: { type: Array, default: () => [] },
})

const showDialog = ref(false)

const source = computed(() => ({
  doctype: props.doctype,
  name: props.name,
  contacts: contactChoices(props.contacts),
}))
</script>
