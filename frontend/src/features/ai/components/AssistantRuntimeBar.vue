<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { Check, ChevronDown } from '@lucide/vue'
import { Button } from '@/shared/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/shared/components/ui/popover'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/shared/components/ui/command'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
import type { AiProviderProfile } from '@/shared/types/ai_assistant'

export type ThinkingLevel = 'off' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'
const THINKING_OPTIONS: { value: ThinkingLevel; label: string; hint: string }[] = [
  { value:'off', label:'关闭', hint:'不请求推理' }, { value:'low', label:'低', hint:'轻量推理' },
  { value:'medium', label:'中', hint:'平衡' }, { value:'high', label:'高', hint:'更深推理' },
  { value:'xhigh', label:'极高', hint:'更重推理' }, { value:'max', label:'最大', hint:'最深推理' },
]
const props = defineProps<{ providers:AiProviderProfile[]; provider:string; model:string; thinking:ThinkingLevel; disabled?:boolean }>()
const emit = defineEmits<{ select:[payload:{provider:string;model:string}]; thinking:[level:ThinkingLevel] }>()
const mobile = useMobileLayout()
const modelOpen = ref(false), thinkingOpen = ref(false)
const modelId = useId(), thinkingId = useId()
const pair = (provider:string, model:string) => JSON.stringify([provider, model])
const modelValue = computed(() => pair(props.provider, props.model))
const groups = computed(() => props.providers.filter(p => p.is_active !== false && p.models.length).map(p => ({
  name:p.name, isDefault:p.is_default,
  models:[...new Set(p.models)].filter(model => !p.model_catalog?.some(item => item.id === model && item.enabled === false)),
})).filter(p => p.models.length))
const thinkingLabel = computed(() => THINKING_OPTIONS.find(item => item.value === props.thinking)?.label ?? '关闭')
function selectModel(provider:string, model:string): void {
  if (props.disabled) return
  modelOpen.value = false
  emit('select', {provider, model})
}
function selectThinking(level:ThinkingLevel): void {
  if (props.disabled) return
  thinkingOpen.value = false
  emit('thinking', level)
}
function onOpenAutoFocus(event:Event): void {
  // On a phone, opening a picker should not also launch the keyboard and move the composer.
  if (mobile.value) {
    event.preventDefault()
    const id = modelOpen.value ? modelId : thinkingId
    requestAnimationFrame(() => document.getElementById(id)?.focus({preventScroll:true}))
  }
}
watch(() => props.disabled, disabled => { if (disabled) { modelOpen.value = false; thinkingOpen.value = false } })
</script>

<template>
  <div class="assistant-runtime" role="group" aria-label="模型与思考">
    <Popover v-model:open="modelOpen">
      <PopoverTrigger as-child>
        <Button access="read" class="assistant-runtime__model" variant="ghost" role="combobox" :aria-controls="modelId" :aria-expanded="modelOpen" aria-label="选择供应商与模型" :title="model ? `${model} · ${provider}` : '选择模型'" :disabled="disabled || !groups.length">
          <span>{{ model || '选择模型' }}</span><ChevronDown aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent :id="modelId" class="assistant-runtime-picker assistant-model-picker" side="top" align="start" :collision-padding="12" :side-offset="8" tabindex="-1" aria-label="选择模型" @open-auto-focus="onOpenAutoFocus">
        <Command :model-value="modelValue">
          <CommandInput :auto-focus="!mobile" placeholder="搜索模型或供应商" aria-label="搜索模型或供应商" />
          <CommandList>
            <CommandEmpty>没有匹配的模型</CommandEmpty>
            <CommandGroup v-for="group in groups" :key="group.name" :heading="group.isDefault ? `${group.name} · 默认` : group.name">
              <CommandItem v-for="item in group.models" :key="pair(group.name,item)" :value="pair(group.name,item)" :text-value="`${item} ${group.name}`" @select="selectModel(group.name,item)">
                <Check class="runtime-check" :class="{ invisible:provider !== group.name || model !== item }" aria-hidden="true" />
                <span class="runtime-option"><span>{{ item }}</span><small>{{ group.name }}</small></span>
              </CommandItem>
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
    <Popover v-model:open="thinkingOpen">
      <PopoverTrigger as-child>
        <Button access="read" class="assistant-runtime__thinking" variant="ghost" role="combobox" :aria-expanded="thinkingOpen" :aria-controls="thinkingId" :aria-label="`思考强度：${thinkingLabel}`" :disabled="disabled">
          <span>推理：{{ thinkingLabel }}</span><ChevronDown aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent :id="thinkingId" class="assistant-runtime-picker assistant-thinking-picker" side="top" align="end" :collision-padding="12" :side-offset="8" tabindex="-1" aria-label="思考强度" @open-auto-focus="onOpenAutoFocus">
        <Command :model-value="thinking"><CommandList>
          <CommandItem v-for="item in THINKING_OPTIONS" :key="item.value" :value="item.value" :text-value="item.label" @select="selectThinking(item.value)">
            <Check class="runtime-check" :class="{ invisible:thinking !== item.value }" aria-hidden="true" />
            <span class="runtime-option"><span>{{ item.label }}</span><small>{{ item.hint }}</small></span>
          </CommandItem>
        </CommandList></Command>
      </PopoverContent>
    </Popover>
  </div>
</template>

<style scoped>
.assistant-runtime { display:flex; align-items:center; flex-wrap:nowrap; gap:4px; min-width:0; }
.assistant-runtime__model { flex:1 1 170px; min-width:0; max-width:240px; justify-content:space-between; }
.assistant-runtime__thinking { flex:none; min-width:86px; justify-content:space-between; }
.assistant-runtime > button { height:34px; padding:0 8px; border:0; border-radius:8px; background:transparent; font-size:13px; font-weight:500; box-shadow:none; color:var(--text-secondary); }
.assistant-runtime > button span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0; }
.assistant-runtime > button svg { width:12px; height:12px; flex:none; color:var(--text-tertiary); }
.assistant-runtime > button:hover,.assistant-runtime > button[aria-expanded='true'] { background:var(--surface-hover); color:var(--text-primary); }
.assistant-runtime-picker { padding:4px; border-radius:12px; width:min(350px,calc(100vw - 24px)); max-height:min(370px,var(--reka-popover-content-available-height)); display:flex; overflow:hidden; }
.assistant-runtime-picker :deep([data-slot='command']) { height:auto; min-height:0; max-height:inherit; }
.assistant-runtime-picker :deep([data-slot='command-list']) { min-height:0; max-height:calc(min(370px,var(--reka-popover-content-available-height)) - 58px); overflow-y:auto; overscroll-behavior:contain; }
.assistant-runtime-picker :deep([data-slot='command-item']) { min-height:44px; align-items:center; padding:8px; gap:8px; cursor:pointer; }
.assistant-runtime-picker :deep([data-slot='command-input']) { font-size:16px; }
.assistant-runtime-picker :deep([data-slot='command-group-heading']) { color:var(--text-tertiary); font-size:11px; padding:8px; }
.runtime-check { width:16px; height:16px; flex:none; }
.runtime-option { display:flex; flex-direction:column; gap:3px; min-width:0; width:100%; }
.runtime-option > span { font-size:13px; line-height:1.4; overflow-wrap:anywhere; }
.runtime-option > small { font-size:11px; color:var(--text-tertiary); line-height:1.3; }
.assistant-thinking-picker { width:210px; }
.assistant-thinking-picker :deep([data-slot='command-list']) { max-height:var(--reka-popover-content-available-height); }
.assistant-thinking-picker .runtime-option { flex-direction:row; justify-content:space-between; align-items:center; }
@media(max-width:767px) {
  .assistant-runtime { flex:1 1 0%; gap:2px; }
  .assistant-runtime__model { width:0; max-width:none; flex:1 1 0%; }
  .assistant-runtime__thinking { min-width:76px; width:76px; }
  .assistant-runtime > button { height:36px; padding:0 4px; font-size:12px; gap:3px; }
}
</style>
