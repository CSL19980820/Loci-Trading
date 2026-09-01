<script setup lang="ts">
/*
 * 大屏空态 —— 默认「极窄一行」。
 *
 * 旧版每个子块都渲染「标题 + 原因 + 下一步」三行长文案，收盘时一屏里同一句话
 * 出现七遍，还把块内高度撑变形。现在默认形态是：一行 ≤8 字的灰字，整块高度
 * 钉死 ≤ 40px，块内其他元素位置不因为有没有数据而移动。
 *
 * `verbose` 是逃生舱：只给「全屏唯一的会话级声明」用（当前由 LiveTopBar 的胶囊
 * 承担）。业务子块传 verbose 视为 review 阻断项。
 */
import { computed } from 'vue'
import type { ConnectionStatus } from '../composables/useLiveBoard'
import { blockHint, describeSession } from '../lib/sessionCopy'

const props = withDefaults(
  defineProps<{
    /** 块内短语，≤8 字，例如「无信号」「榜单待开盘」 */
    hint?: string
    status?: ConnectionStatus
    isLive?: boolean
    sessionPhase?: string
    /** 会话级长文案；全屏只允许一处 */
    verbose?: boolean
  }>(),
  {
    hint: '暂无数据',
    status: undefined,
    isLive: undefined,
    sessionPhase: undefined,
    verbose: false,
  },
)

const text = computed<string>(() => {
  if (props.verbose) {
    return describeSession(props.status ?? 'connecting', props.isLive, props.sessionPhase).text
  }
  return blockHint(props.status, props.hint)
})

const tone = computed<string>(() =>
  props.status === 'offline' || props.status === 'reconnecting' ? 'warn' : 'idle',
)
</script>

<template>
  <div class="live-empty" :class="[`live-empty--${tone}`, { 'live-empty--verbose': verbose }]">
    <span class="live-empty__text">{{ text }}</span>
  </div>
</template>

<style scoped>
/* 定高 40px：空/非空切换时块内布局零位移 */
.live-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  max-height: 40px;
  padding: var(--gap-1) var(--gap-2);
  font-family: var(--live-font-sans);
}

.live-empty__text {
  font-size: var(--fs-kicker);
  line-height: 1.4;
  letter-spacing: 0.08em;
  color: var(--live-dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.live-empty--warn .live-empty__text {
  color: var(--live-warn);
}

.live-empty--verbose .live-empty__text {
  letter-spacing: 0.02em;
  color: var(--live-muted);
}
</style>
