<script setup lang="ts">
import { computed } from 'vue'
import { Input } from '../input'
import { Button } from '../button'
import { Popover, PopoverTrigger, PopoverContent } from '../popover'
const props = defineProps<{ modelValue?: string | null; predefine?: string[]; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string]; change: [value: string] }>()
const value = computed(() => /^#[0-9a-f]{6}$/i.test(props.modelValue ?? '') ? props.modelValue! : '#2563eb')
function update(next: string) { if (!/^#[0-9a-f]{6}$/i.test(next)) return; emit('update:modelValue', next); emit('change', next) }
</script>
<template>
  <Popover><PopoverTrigger as-child><Button access="read" type="button" variant="outline" class="color-field" :disabled="disabled" :aria-label="$attrs['aria-label'] as string || '选择颜色'"><span class="color-field__swatch" :style="{ background: value }" /><span>{{ value }}</span></Button></PopoverTrigger>
    <PopoverContent class="color-field__popup"><Input type="color" :model-value="value" aria-label="调色板" @update:model-value="next => update(String(next))" /><Input :model-value="value" aria-label="十六进制颜色" @update:model-value="next => update(String(next))" />
      <div class="color-field__presets"><Button access="read" variant="ghost" v-for="color in predefine ?? []" :key="color" type="button" class="color-field__swatch" :style="{ background: color }" :aria-label="color" @click="update(color)" /></div>
    </PopoverContent>
  </Popover>
</template>
