<template>
  <div class="flex flex-col gap-2">
    <div v-for="(row, index) in rows" :key="index" class="flex items-end gap-2">
      <FormControl
        class="w-48"
        type="select"
        :label="index === 0 ? __('Document type') : ''"
        :model-value="row.document_type"
        :options="documentTypes.map((value) => ({ label: __(value), value }))"
        @update:model-value="(value) => changeType(row, value)"
      />
      <FormControl
        class="flex-1"
        type="select"
        :label="index === 0 ? __('Field') : ''"
        :model-value="row.fieldname"
        :options="fieldOptions(row)"
        @update:model-value="(value) => (row.fieldname = value)"
      />
      <Button
        icon="lucide-x"
        variant="ghost"
        :tooltip="__('Remove')"
        @click="rows.splice(index, 1)"
      />
    </div>
    <div>
      <Button iconLeft="lucide-plus" :label="__('Add field')" @click="addRow" />
    </div>
  </div>
</template>

<script setup>
import { runAction } from '@/components/ErasureRequests/erasureApi'
import { FormControl } from 'frappe-ui'
import { reactive, watch } from 'vue'

const props = defineProps({
  documentTypes: { type: Array, required: true },
})

// [{ document_type, fieldname }]: the page saves the whole list.
const rows = defineModel({ type: Array, required: true })

// Field choices per document type, from the doctype's meta (custom fields included).
const choices = reactive({})

async function load(documentType) {
  if (!documentType || documentType in choices) return
  choices[documentType] = []
  const fields = await runAction('settings.get_personal_field_choices', {
    document_type: documentType,
  })
  if (fields) choices[documentType] = fields
  else delete choices[documentType]
}

watch(
  () => rows.value.map((row) => row.document_type),
  (types) => types.forEach(load),
  { immediate: true },
)

// A saved field that the choices do not list (none today) must still show.
function fieldOptions(row) {
  const options = (choices[row.document_type] || []).map((field) => ({
    label: `${field.label} (${field.fieldname})`,
    value: field.fieldname,
  }))
  if (
    row.fieldname &&
    !options.some((option) => option.value === row.fieldname)
  ) {
    options.unshift({ label: row.fieldname, value: row.fieldname })
  }
  return [{ label: '', value: '' }, ...options]
}

function changeType(row, documentType) {
  row.document_type = documentType
  row.fieldname = ''
}

function addRow() {
  rows.value.push({ document_type: props.documentTypes[0], fieldname: '' })
}
</script>
