<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/shared/lib/utils'
export interface DescriptionItem {
  key: string
  label: string
  value?: string | number | null
  wide?: boolean
  mono?: boolean
  tone?: 'positive' | 'negative'
}
defineProps<{ items: DescriptionItem[]; class?: HTMLAttributes['class'] }>()
</script>

<template>
  <dl :class="cn('descriptions', $props.class)" data-slot="descriptions">
    <div v-for="item in items" :key="item.key" class="descriptions__item" :class="{ 'is-wide': item.wide }">
      <dt>{{ item.label }}</dt>
      <dd :class="[{ 'is-mono': item.mono }, item.tone]">
        <slot :name="item.key" :item="item">{{ item.value === '' || item.value == null ? '—' : item.value }}</slot>
      </dd>
    </div>
  </dl>
</template>

<style scoped>
.descriptions { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:1px; margin:0; border:1px solid var(--border-subtle); border-radius:9px; overflow:hidden; background:var(--border-subtle); font-size:13px; line-height:1.8; }
.descriptions__item { display:grid; grid-template-columns:96px minmax(0,1fr); min-width:0; background:var(--surface); }
.descriptions__item.is-wide { grid-column:1/-1; }
.descriptions dt { padding:11px 12px; margin:0; color:var(--text-secondary); background:var(--surface-sunken); font-weight:400; }
.descriptions dd { padding:11px 14px; margin:0; color:var(--text-primary); white-space:pre-wrap; overflow-wrap:anywhere; min-width:0; }
.descriptions .is-mono { font-variant-numeric:tabular-nums; }
.descriptions .positive { color:var(--up); }.descriptions .negative { color:var(--down); }
@media(max-width:640px) {
 .descriptions { grid-template-columns:minmax(0,1fr); font-size:13px; }
 .descriptions__item { grid-template-columns:96px minmax(0,1fr); }
 .descriptions dt { padding:9px 10px; }.descriptions dd { padding:9px 11px; }
}
</style>
