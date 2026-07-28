<script setup lang="ts">
withDefaults(
  defineProps<{
    modelValue: string
    placeholder?: string
    busy?: boolean
    queryLabel?: string
    maxlength?: number
  }>(),
  {
    placeholder: '',
    busy: false,
    queryLabel: '查询',
    maxlength: undefined,
  },
)

const emit = defineEmits<{
  'update:modelValue': [string]
  query: []
}>()
</script>

<template>
  <section class="query-filter-bar">
    <el-input
      :model-value="modelValue"
      :placeholder="placeholder"
      :maxlength="maxlength"
      clearable
      class="query-filter-bar__input"
      @update:model-value="emit('update:modelValue', String($event ?? ''))"
      @keydown.enter.prevent="emit('query')"
    />
    <el-button type="primary" :loading="busy" @click="emit('query')">{{ queryLabel }}</el-button>
    <slot />
  </section>
</template>
