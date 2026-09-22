<script setup lang="ts">
import { Inbox } from '@lucide/vue'
import { computed, type Component } from 'vue'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/shared/components/ui/empty'
const props = withDefaults(defineProps<{ description?:string; reason?:string; eta?:string; icon?:Component; compact?:boolean; imageSize?:number }>(), {description:'这里还没有记录',compact:false})
const hint = computed(() => [props.reason,props.eta ? `预计 ${props.eta}` : ''].filter(Boolean).join('；'))
</script>
<template>
  <Empty class="empty-state" :class="{ 'empty-state--compact':compact }">
    <EmptyHeader class="empty-state__header"><EmptyMedia variant="icon" class="empty-state__icon"><component :is="icon ?? Inbox" aria-hidden="true" /></EmptyMedia><EmptyTitle class="empty-state__title">{{ description }}</EmptyTitle><EmptyDescription v-if="hint" :title="hint" class="empty-state__hint">{{ hint }}</EmptyDescription></EmptyHeader>
    <EmptyContent v-if="$slots.default" class="empty-state__actions"><slot /></EmptyContent>
  </Empty>
</template>
<style scoped>
.empty-state { flex:1 1 auto; width:100%; min-height:0; padding:24px 16px; }
.empty-state__header { max-width:100%; gap:8px; }.empty-state__title { font-size:14px; font-weight:550; overflow-wrap:anywhere; }
.empty-state__hint { max-width:44ch; font-size:12px; overflow-wrap:anywhere; }
.empty-state__actions { flex-direction:row; flex-wrap:wrap; justify-content:center; gap:8px; }
.empty-state--compact { flex-direction:row; gap:10px; padding:16px; }
.empty-state--compact .empty-state__header { flex-direction:row; justify-content:center; gap:8px; }.empty-state--compact .empty-state__icon { width:28px; height:28px; margin:0; }.empty-state--compact .empty-state__icon :deep(svg) { width:14px; height:14px; }
.empty-state--compact .empty-state__title { font-size:13px; font-weight:400; }.empty-state--compact .empty-state__hint { display:none; }.empty-state--compact .empty-state__actions { width:auto; margin:0 0 0 auto; }
</style>
