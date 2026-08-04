<script setup lang="ts">
import { computed, useSlots } from 'vue'

const props = withDefaults(
  defineProps<{
    /** 左侧区域宽度 */
    leftWidth?: string
    /** 容器内边距（纸色沟槽已在 main-content；此处多为内容卡内边距） */
    padding?: string
    /** 左右区域间距 */
    gap?: string
  }>(),
  {
    leftWidth: '230px',
    padding: '0',
    gap: '0.75rem',
  },
)

const slots = useSlots()
const hasLeft = computed(() => Boolean(slots.left))
const hasSearch = computed(() => Boolean(slots.search))
const hasMain = computed(() => Boolean(slots.main))
const hasTopExpand = computed(() => Boolean(slots.topExpand))
</script>

<template>
  <div
    class="page-container"
    :style="{
      '--pc-left-width': leftWidth,
      '--pc-padding': padding,
      '--pc-gap': gap,
    }"
  >
    <aside v-if="hasLeft" class="page-container__left">
      <slot name="left" />
    </aside>
    <div class="page-container__body">
      <slot v-if="hasTopExpand" name="topExpand" />
      <div v-if="hasSearch" class="page-container__search">
        <slot name="search" />
      </div>
      <div v-if="hasMain" class="page-container__main">
        <slot name="main" />
      </div>
      <slot />
    </div>
  </div>
</template>

<style scoped>
.page-container {
  width: 100%;
  height: 100%;
  min-height: 0;
  display: flex;
  padding: var(--pc-padding);
  gap: var(--pc-gap);
  position: relative;
  flex: 1 1 auto;
  overflow: hidden;
}

.page-container__left {
  width: var(--pc-left-width);
  flex-shrink: 0;
  height: 100%;
  min-height: 0;
  overflow: auto;
  border-right: 1px solid var(--rule);
  background: var(--panel-2);
}

.page-container__body {
  width: 0;
  flex: 1;
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: transparent;
}

.page-container__search {
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: flex-start;
  padding: 0.75rem 1rem 0;
  border-bottom: 1px solid var(--rule);
}

.page-container__main {
  flex: 1;
  width: 100%;
  min-width: 0;
  min-height: 0;
  height: 0;
  padding: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
</style>
