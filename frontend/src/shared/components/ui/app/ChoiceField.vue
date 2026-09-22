<script setup lang="ts" generic="T = string">
import { computed, nextTick, ref, useAttrs, useSlots, watch, type StyleValue } from 'vue'
import { Check, ChevronsUpDown, LoaderCircle, X } from '@lucide/vue'
import { Button } from '../button'
import { Popover, PopoverContent, PopoverTrigger } from '../popover'
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from '../command'
import { collectChoices, type ChoiceEntry } from './choiceOptions'
import { encodeChoice, useFieldControl } from './context'
import { VNodeContent } from './vnodeContent'

defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{
  modelValue?: T; options?: ChoiceEntry[]; multiple?: boolean; filterable?: boolean;
  clearable?: boolean; allowCreate?: boolean; disabled?: boolean; busy?: boolean;
  placeholder?: string; size?: string; popperClass?: string
}>(), { placeholder: '请选择' })
const emit = defineEmits<{ 'update:modelValue': [value: T]; change: [value: T]; clear: []; 'visible-change': [open: boolean] }>()
const slots = useSlots()
const attrs = useAttrs()
const field = useFieldControl()
const root = ref<HTMLElement>()
const open = ref(false)
const query = ref('')
const disabled = computed(() => props.disabled || field.disabled.value)
const selections = computed<unknown[]>(() => props.multiple
  ? (Array.isArray(props.modelValue) ? props.modelValue : [])
  : props.modelValue == null ? [] : [props.modelValue])
function options() { return props.options ?? collectChoices(slots.default?.() ?? []) }
function labelOf(value: unknown) { return options().find(option => encodeChoice(option.value) === encodeChoice(value))?.label ?? String(value ?? '') }
function selected(value: unknown) { return selections.value.some(item => encodeChoice(item) === encodeChoice(value)) }
function update(next: unknown) { emit('update:modelValue', next as T); emit('change', next as T); field.validate() }
function choose(value: unknown) {
  if (disabled.value) return
  if (props.multiple) update(selected(value) ? selections.value.filter(item => encodeChoice(item) !== encodeChoice(value)) : [...selections.value, value])
  else { update(value); open.value = false }
  query.value = ''
}
async function clear() {
  if (disabled.value) return
  update(props.multiple ? [] : '')
  emit('clear')
  await nextTick()
  root.value?.querySelector<HTMLButtonElement>('.choice-field__trigger')?.focus()
}
function controlAttrs() { return { ...field.bindings.value, ...Object.fromEntries(Object.entries(attrs).filter(([key]) => key !== 'class' && key !== 'style')) } }
watch(open, value => { if (!value) query.value = ''; emit('visible-change', value) })
watch(disabled, value => { if (value) open.value = false })
</script>

<template>
  <div ref="root" :class="['choice-field', attrs.class]" :style="attrs.style as StyleValue">
    <Popover v-model:open="open">
      <PopoverTrigger as-child>
        <Button access="read" v-bind="controlAttrs()" type="button" variant="outline" class="choice-field__trigger" role="combobox"
          :disabled="disabled" :aria-expanded="open" :aria-busy="busy || undefined" :title="selections.map(labelOf).join('、') || placeholder"
          @keydown.down.prevent="open = true" @keydown.up.prevent="open = true">
          <span v-if="multiple && selections.length" class="choice-field__values">{{ selections.map(labelOf).join('、') }}</span>
          <span v-else-if="!multiple && selections.length" class="choice-field__value">{{ labelOf(selections[0]) || placeholder }}</span>
          <span v-else class="text-muted-foreground">{{ placeholder }}</span>
          <LoaderCircle v-if="busy" class="size-4 shrink-0 animate-spin" aria-hidden="true" />
          <ChevronsUpDown v-else class="size-4 shrink-0 opacity-60" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent :class="['choice-field__popup', popperClass]" align="start" :side-offset="4" :collision-padding="8">
        <Command :model-value="multiple ? selections.map(encodeChoice) : encodeChoice(modelValue)" :multiple="multiple">
          <CommandInput v-if="filterable || allowCreate" placeholder="搜索…" aria-label="搜索选项" @update:model-value="query = String($event)" />
          <CommandList>
            <CommandEmpty>{{ busy ? '加载中…' : query ? '没有匹配的选项' : '暂无可选数据' }}</CommandEmpty>
            <template v-for="(option, index) in options()" :key="encodeChoice(option.value)">
              <div v-if="option.group && (index === 0 || options()[index - 1]?.group !== option.group)" class="choice-field__group">{{ option.group }}</div>
              <CommandItem :text-value="option.label" :value="encodeChoice(option.value)" :disabled="option.disabled" @select="choose(option.value)">
                <Check class="size-4" :class="selected(option.value) ? 'opacity-100' : 'opacity-0'" aria-hidden="true" />
                <VNodeContent v-if="option.render" :render="option.render" />
                <span v-else>{{ option.label }}</span>
              </CommandItem>
            </template>
            <CommandItem v-if="allowCreate && query.trim() && !options().some(option => option.label === query.trim())"
              :value="query.trim()" @select="choose(query.trim())">使用“{{ query.trim() }}”</CommandItem>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
    <Button access="read" variant="ghost" v-if="clearable && selections.length && !disabled && (multiple || modelValue !== '')" class="choice-field__clear field-icon-button"
      type="button" aria-label="清空选择" @click="clear"><X class="size-3.5" /></Button>
  </div>
</template>
