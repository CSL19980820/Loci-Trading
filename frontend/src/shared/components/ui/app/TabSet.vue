<script setup lang="ts" generic="T = string">
import { ref, useSlots } from 'vue'
import { Tabs, TabsList, TabsTrigger } from '../tabs'
import { encodeChoice, decodeChoice } from './context'
import { componentName, flattenNodes, nodeSlot, VNodeContent } from './vnodeContent'
const props = defineProps<{ modelValue?: T }>()
const emit = defineEmits<{ 'update:modelValue': [value: T]; 'tab-change': [value: T] }>()
const slots = useSlots()
const local = ref<unknown>(undefined)
function pages() {
  return flattenNodes(slots.default?.()).filter(node => componentName(node) === 'TabPage').map(node => ({
    name: node.props?.name, label: String(node.props?.label ?? node.props?.name ?? ''),
    disabled: node.props?.disabled === '' || Boolean(node.props?.disabled), render: nodeSlot(node, 'label'),
  }))
}
function update(value: string | number) {
  const next = decodeChoice(String(value)) as T
  local.value = next
  emit('update:modelValue', next)
  emit('tab-change', next)
}
</script>
<template>
  <Tabs class="tab-set" :model-value="encodeChoice(modelValue ?? local ?? pages()[0]?.name)" @update:model-value="update">
    <TabsList class="tab-set__list" :aria-label="$attrs['aria-label'] as string">
      <TabsTrigger v-for="page in pages()" :key="encodeChoice(page.name)" :value="encodeChoice(page.name)" :disabled="page.disabled">
        <VNodeContent v-if="page.render" :render="page.render" /><template v-else>{{ page.label }}</template>
      </TabsTrigger>
    </TabsList>
    <slot />
  </Tabs>
</template>
