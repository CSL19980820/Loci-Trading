<script setup lang="ts">
import { computed, type Component } from 'vue'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
import { Button } from '@/shared/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/shared/components/ui/tabs'

export interface AgentWorkspaceNavItem {
  name: string
  label: string
  badge?: string | number
  disabled?: boolean
  icon?: Component
}

const props = withDefaults(defineProps<{
  modelValue: string
  panelId: string
  items: AgentWorkspaceNavItem[]
  ariaLabel?: string
}>(), { ariaLabel: '智能体工作区' })
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const mobile = useMobileLayout()
const value = computed({
  get: () => props.modelValue,
  set: (next: string | number) => {
    const name = String(next)
    const item = props.items.find(item => item.name === name)
    if (item && !item.disabled && name !== props.modelValue) emit('update:modelValue', name)
  },
})
</script>

<template>
  <nav class="agent-workspace-nav" :aria-label="ariaLabel">
    <Tabs v-model="value" :orientation="mobile ? 'horizontal' : 'vertical'" class="agent-workspace-nav__tabs">
      <TabsList class="agent-workspace-nav__list" :aria-label="ariaLabel">
        <TabsTrigger v-for="item in items" :key="item.name" :value="item.name" as-child :disabled="item.disabled">
          <Button access="read" variant="ghost" type="button" class="agent-workspace-nav__item"
            :id="`${panelId}-tab-${item.name}`" :aria-controls="panelId" :disabled="item.disabled">
            <component :is="item.icon" v-if="item.icon" class="agent-workspace-nav__icon" aria-hidden="true" />
            <span class="agent-workspace-nav__label">{{ item.label }}</span>
            <span v-if="item.badge != null && item.badge !== ''" class="agent-workspace-nav__badge">{{ item.badge }}</span>
          </Button>
        </TabsTrigger>
      </TabsList>
    </Tabs>
    <div v-if="$slots.footer" class="agent-workspace-nav__footer"><slot name="footer" /></div>
  </nav>
</template>

<style scoped>
.agent-workspace-nav {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
  min-height: 0;
  padding: 10px 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: color-mix(in oklab, var(--surface) 82%, var(--surface-canvas));
}
.agent-workspace-nav__tabs { flex: 1 1 auto; min-height: 0; gap: 0; }
.agent-workspace-nav__list {
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  align-items: stretch;
  gap: 4px;
  width: 100%;
  height: auto;
  min-height: 0;
  padding: 0;
  overflow-y: auto;
  overflow-x: hidden;
  border-radius: 0;
  background: transparent;
}
.agent-workspace-nav__item {
  position: relative;
  flex: 0 0 auto;
  justify-content: flex-start;
  gap: 8px;
  width: 100%;
  min-height: 39px;
  height: auto;
  padding: 9px 10px;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  border-radius: var(--radius);
}
.agent-workspace-nav__item[data-state='active'] {
  color: var(--seal-ink);
  background: var(--seal-soft);
  font-weight: 650;
}
.agent-workspace-nav__item[data-state='active']::before {
  content: '';
  position: absolute;
  inset: 10px auto 10px 0;
  width: 2px;
  border-radius: 2px;
  background: var(--seal);
}
.agent-workspace-nav__icon { flex: none; width: 16px; height: 16px; opacity: .8; }
.agent-workspace-nav__label { min-width: 0; white-space: normal; text-align: left; line-height: 1.35; }
.agent-workspace-nav__badge {
  flex: none;
  margin-left: auto;
  font: 500 11px / 1.3 var(--mono);
  font-variant-numeric: tabular-nums;
  opacity: .8;
}
.agent-workspace-nav__footer {
  flex: 0 0 auto;
  padding: 10px 6px 2px;
  border-top: 1px solid var(--border-subtle);
  color: var(--text-tertiary);
  font-size: 11px;
  line-height: 1.7;
  overflow-wrap: anywhere;
}
@media (max-width: 767px) {
  .agent-workspace-nav { flex: 0 0 auto; gap: 4px; padding: 4px; border-radius: var(--radius); }
  .agent-workspace-nav__tabs { flex: none; }
  .agent-workspace-nav__list { flex-direction: row; gap: 2px; overflow-x: auto; overflow-y: hidden; scrollbar-width: thin; }
  .agent-workspace-nav__item { width: auto; min-height: 38px; padding: 8px 11px; font-size: 12px; }
  .agent-workspace-nav__label { white-space: nowrap; }
  .agent-workspace-nav__icon { width: 14px; height: 14px; }
  .agent-workspace-nav__badge { margin-left: 0; }
  .agent-workspace-nav__item[data-state='active']::before { inset: auto 11px 0; width: auto; height: 2px; }
  .agent-workspace-nav__footer { padding: 4px 7px; }
}
</style>
