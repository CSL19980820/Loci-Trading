<script setup lang="ts">
import { computed } from 'vue'

/**
 * 空态 —— 一行主文案 + 最多一个主操作，铺满父级剩余高度并居中。
 *
 * 旧版锁 `max-h-24`（96px）：文案自己是小岛，主区剩一大片白。
 * 规范：主文案 ≤14 字讲「为什么空」，`reason` 一行讲「下一步」，
 * 两者合计 ≤24 字；插图一律不要。高度吃满父级，内容居中。
 */
const props = withDefaults(
  defineProps<{
    /** 为什么空，≤14 字 */
    description?: string
    /** 下一步做什么；与 description 合计 ≤24 字，单行显示 */
    reason?: string
    /** 可选：预计恢复/产出时间，接在 reason 后同一行 */
    eta?: string
    /** @deprecated 空态不再有插图，保留仅为不破坏存量调用 */
    imageSize?: number
  }>(),
  {
    // 默认值不该是一句可以直接交付的墓碑：调用方应当讲清「这里会出现什么」
    description: '这里还没有记录',
  },
)

const hint = computed(() => {
  const parts = [props.reason, props.eta ? `预计 ${props.eta}` : ''].filter(Boolean)
  return parts.join('；')
})
</script>

<template>
  <div class="empty-state flex h-full min-h-0 min-w-0 w-full flex-1 flex-col items-center justify-center gap-2 overflow-hidden px-3 py-6 text-center">
    <p class="empty-state__title text-body text-ink m-0 max-w-full leading-snug font-medium break-words">{{ description }}</p>
    <el-tooltip
      v-if="hint"
      :content="hint"
      placement="top"
      :show-after="200"
      trigger="hover"
    >
      <p class="empty-state__hint text-aux text-mist m-0 max-w-[52ch] leading-snug [display:-webkit-box] [-webkit-line-clamp:2] [-webkit-box-orient:vertical] overflow-hidden">{{ hint }}</p>
    </el-tooltip>
    <div v-if="$slots.default" class="mt-px flex items-center gap-2">
      <slot />
    </div>
  </div>
</template>
