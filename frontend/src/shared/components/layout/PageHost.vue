<script setup lang="ts">
/**
 * 主区路由宿主：非档案页 KeepAlive；档案页 Teleport 全屏蒙版，底下源页不销毁。
 */
import { watch, type Component as VueComponent } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'

const props = defineProps<{
  component: VueComponent | null
  route: RouteLocationNormalizedLoaded
}>()

/** KeepAlive 卸下后，ECharts 挂在 body 的 tooltip 可能残留并盖住蒙版。 */
function scrubOrphanChartTips(): void {
  document.querySelectorAll<HTMLElement>('div[class*="echarts-tooltip"]').forEach((el) => {
    if (!el.closest('.archive-overlay')) el.style.display = 'none'
  })
}

watch(
  () => props.route.name,
  (name) => {
    if (name === 'archive') scrubOrphanChartTips()
  },
)
</script>

<template>
  <KeepAlive :max="12">
    <component
      :is="component"
      v-if="component && route.name !== 'archive'"
      :key="String(route.name)"
    />
  </KeepAlive>
  <Teleport to="body">
    <div
      v-if="component && route.name === 'archive'"
      class="archive-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="个股档案"
    >
      <component :is="component" :key="route.fullPath" />
    </div>
  </Teleport>
</template>
