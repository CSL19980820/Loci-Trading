<script setup lang="ts">
/**
 * 主区路由宿主：非档案页 KeepAlive；档案页 Teleport 全屏蒙版，底下源页不销毁。
 */
import { ref, watch, type Component as VueComponent } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/shared/components/ui/dialog'
import CachedRoutePage from './CachedRoutePage.vue'

const props = defineProps<{
  component: VueComponent | null
  route: RouteLocationNormalizedLoaded
}>()

const archivePage = ref<{ close: () => void } | null>(null)
const focusOrigin = ref<HTMLElement | null>(null)
function restoreFocus(event: Event): void {
  event.preventDefault()
  if (focusOrigin.value?.isConnected) focusOrigin.value.focus()
}

/** KeepAlive 卸下后，ECharts 挂在 body 的 tooltip 可能残留并盖住蒙版。 */
function scrubOrphanChartTips(): void {
  document.querySelectorAll<HTMLElement>('div[class*="echarts-tooltip"]').forEach((el) => {
    if (!el.closest('.archive-overlay')) el.style.display = 'none'
  })
}

watch(
  () => props.route.name,
  (name) => {
    if (name === 'archive') {
      focusOrigin.value = document.activeElement instanceof HTMLElement ? document.activeElement : null
      scrubOrphanChartTips()
    }
  },
)
</script>

<template>
  <KeepAlive :max="12">
    <CachedRoutePage
      :component="component!"
      v-if="component && route.name !== 'archive'"
      :key="String(route.name)"
    />
  </KeepAlive>
  <Dialog :open="Boolean(component && route.name === 'archive')">
    <DialogContent unstyled :show-close-button="false" :show-overlay="false"
      class="archive-overlay fixed inset-0 z-[var(--z-archive)] flex h-full w-full flex-col overflow-hidden"
      @escape-key-down.prevent="archivePage?.close()" @pointer-down-outside.prevent @close-auto-focus="restoreFocus">
      <DialogTitle class="sr-only">个股档案</DialogTitle>
      <DialogDescription class="sr-only">查看个股行情、研究和记录；关闭后返回原页面。</DialogDescription>
      <component ref="archivePage" :is="component!" :key="route.fullPath" />
    </DialogContent>
  </Dialog>
</template>
