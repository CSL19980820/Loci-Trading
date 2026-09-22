<script setup lang="ts">
import { Button } from '@/shared/components/ui/button'
import { computed, nextTick, ref, useAttrs, watch, type Component, type StyleValue, type CSSProperties } from 'vue'
import { Eye, EyeOff, X } from '@lucide/vue'
import { Input } from '../input'
import { Textarea } from '../textarea'
import { useFieldControl } from './context'

defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{
  modelValue?: unknown; type?: string; disabled?: boolean; clearable?: boolean;
  showPassword?: boolean; prefixIcon?: Component; suffixIcon?: Component;
  rows?: number | string; autosize?: boolean | { minRows?: number; maxRows?: number };
  maxlength?: number | string; showWordLimit?: boolean; size?: string; resize?: CSSProperties['resize']
}>(), { type: 'text' })
const emit = defineEmits<{
  'update:modelValue': [value: string]; input: [value: string]; change: [value: string]; clear: []
}>()
const attrs = useAttrs()
const field = useFieldControl()
const inputRef = ref<{ $el: HTMLInputElement | HTMLTextAreaElement }>()
const revealed = ref(false)
const text = computed(() => String(props.modelValue ?? ''))
const inputType = computed(() => props.showPassword ? (revealed.value ? 'text' : 'password') : props.type)
const controlAttrs = computed(() => {
  const { class: _class, style: _style, ...rest } = attrs
  return { ...field.bindings.value, ...rest }
})
function update(value: string | number) {
  const next = String(value)
  emit('update:modelValue', next)
  emit('input', next)
}
function change(event: Event) {
  emit('change', (event.target as HTMLInputElement).value)
  field.validate()
}
function clear() {
  update('')
  emit('change', '')
  emit('clear')
  field.validate()
  void nextTick(() => inputRef.value?.$el.focus())
}
async function resizeInput() {
  if (props.type !== 'textarea' || !props.autosize) return
  await nextTick()
  const el = inputRef.value?.$el
  if (!el) return
  const settings = typeof props.autosize === 'object' ? props.autosize : {}
  const line = Number.parseFloat(getComputedStyle(el).lineHeight) || 22
  el.style.height = 'auto'
  el.style.height = `${Math.min(Math.max(el.scrollHeight, line * (settings.minRows ?? 2) + 16), line * (settings.maxRows ?? 10) + 16)}px`
}
watch(() => [props.modelValue, props.autosize], resizeInput, { immediate: true, flush: 'post' })
defineExpose({
  focus: () => inputRef.value?.$el.focus(), blur: () => inputRef.value?.$el.blur(),
  input: computed(() => inputRef.value?.$el), textarea: computed(() => inputRef.value?.$el),
})
</script>

<template>
  <div :class="['text-field', attrs.class]" :style="attrs.style as StyleValue">
    <div v-if="$slots.prepend" class="text-field__addon"><slot name="prepend" /></div>
    <div class="text-field__body">
      <span v-if="prefixIcon || $slots.prefix" class="text-field__prefix">
        <slot name="prefix"><component :is="prefixIcon" class="size-4" /></slot>
      </span>
      <Textarea v-if="type === 'textarea'" ref="inputRef" v-bind="controlAttrs" :model-value="text"
        :rows="Number(rows || 3)" :maxlength="maxlength" :disabled="disabled || field.disabled.value"
        class="text-field__control" :style="resize ? { resize } : undefined"
        @update:model-value="update" @change="change" @blur="field.validate" />
      <Input v-else ref="inputRef" v-bind="controlAttrs" :model-value="text" :type="inputType"
        :maxlength="maxlength" :disabled="disabled || field.disabled.value" class="text-field__control"
        :class="{ 'has-prefix': prefixIcon || $slots.prefix, 'has-suffix': clearable || showPassword || suffixIcon || $slots.suffix }"
        @update:model-value="update" @change="change" @blur="field.validate" />
      <span v-if="type !== 'textarea' && (clearable || showPassword || suffixIcon || $slots.suffix)" class="text-field__suffix">
        <Button access="read" variant="ghost" v-if="clearable && text && !disabled && !field.disabled.value" type="button" aria-label="清空输入" class="field-icon-button" @click="clear"><X class="size-3.5" /></Button>
        <Button access="read" variant="ghost" v-if="showPassword" type="button" :disabled="disabled || field.disabled.value" :aria-label="revealed ? '隐藏密码' : '显示密码'" :aria-pressed="revealed" class="field-icon-button" @click="revealed = !revealed"><component :is="revealed ? EyeOff : Eye" class="size-4" /></Button>
        <slot name="suffix"><component :is="suffixIcon" v-if="suffixIcon" class="size-4" /></slot>
      </span>
      <span v-if="showWordLimit && maxlength" class="text-field__count">{{ text.length }} / {{ maxlength }}</span>
    </div>
    <div v-if="$slots.append" class="text-field__addon"><slot name="append" /></div>
  </div>
</template>
