<script setup lang="ts">
import { computed } from 'vue'
import PageTabs, { type PageTabItem } from '@/shared/components/ui/PageTabs.vue'

const props = withDefaults(defineProps<{
  title?: string
  /** Compatibility only: module explanations are not part of the page heading. */
  description?: string
  eyebrow?: string
  tabs?: PageTabItem[]
  tab?: string
  panelId?: string
  compact?: boolean
  sticky?: boolean
  seamless?: boolean
}>(), { compact: false, sticky: false, seamless: false })
const emit = defineEmits<{ 'update:tab': [value: string] }>()
const tabValue = computed({ get: () => props.tab ?? '', set: (value: string) => emit('update:tab', value) })
</script>

<template>
  <header class="page-header" :class="{ 'page-header--compact': compact, 'page-header--sticky': sticky, 'page-header--seamless': seamless, 'page-header--tabbed': tabs?.length }">
    <div class="page-header__row">
      <div class="page-header__lead">
        <div v-if="$slots.leading" class="page-header__leading"><slot name="leading" /></div>
        <h1 v-if="title || $slots.title" class="page-header__title" :class="{ 'sr-only': tabs?.length && !$slots.title }"><slot name="title">{{ title }}</slot></h1>
        <div v-if="$slots.default" class="page-header__meta"><slot /></div>
        <PageTabs v-if="tabs?.length" v-model="tabValue" :items="tabs" :panel-id="panelId" :sticky="false" class="page-header__tabs" />
      </div>
      <div v-if="$slots.actions" class="page-header__actions"><slot name="actions" /></div>
    </div>
  </header>
</template>

<style scoped>
.page-header { flex: none; display: flex; flex-direction: column; gap: 8px; min-width: 0; padding: 8px 0; }
.page-header--sticky { position: sticky; top: 0; z-index: var(--z-sticky); background: var(--surface-canvas); }
.page-header__row { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 12px; min-width: 0; }
.page-header__lead { display: flex; flex-wrap: wrap; flex: 1 1 auto; align-items: center; gap: 8px; min-width: 0; }
.page-header__leading { display: flex; flex: none; align-items: center; }
.page-header__title { display: flex; align-items: center; gap: 8px; margin: 0; min-width: 0; color: var(--text-primary); font-size: 18px; font-weight: 650; line-height: 1.4; letter-spacing: -.025em; }
.page-header--compact .page-header__title { font-size: 17px; }
.page-header__actions { display: flex; flex: 0 1 auto; align-items: center; flex-wrap: wrap; gap: 6px; min-width: 0; max-width: 100%; margin-left: auto; }
.page-header__actions :deep(button) { white-space: nowrap; }
.page-header__meta { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 12px; min-width: 0; font-size: var(--fs-aux); color: var(--text-tertiary); }
.page-header__tabs { min-width: 0; max-width: 100%; margin: 0; flex: 0 1 auto; }
.page-header--tabbed { padding-bottom: 0; }
@media (max-width: 640px) {
  .page-header { padding: 10px 0 8px; gap: 6px; }
  .page-header__row { gap: 6px 8px; }
  .page-header__title, .page-header--compact .page-header__title { font-size: 17px; }
  .page-header__actions { gap: 6px; }
}
</style>
