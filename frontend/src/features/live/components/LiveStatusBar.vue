<script setup lang="ts">
/*
 * 底部状态栏，定高 24px。
 *
 * 除了源/标的/信号计数，它还收编了原先悬在右下角的那句红字「盘中信号未定稿」：
 *   · 红色是价格语义（D1），合规声明不该用红 → 改 --live-dim；
 *   · 悬浮元素在大屏上遮内容 → 并入状态栏右端；
 *   · 长免责声明沉进 tooltip，栏内只留一行短语。
 * 注意：这里**不**复述「已收盘·展示最近快照」——那句归顶栏胶囊，全屏只一处。
 */
import { computed } from 'vue'
import { compactNumber } from '@/shared/lib/format'
import type { ConnectionStatus } from '../composables/useLiveBoard'

const props = defineProps<{
  source: string
  status: ConnectionStatus
  asOf?: string
  quoteCount: number
  signalCount: number
  /** 最近一帧行情距今毫秒；-1=这条流还没喂过数据 */
  staleMs?: number
  /** 采集器最近一次失败原因；空串=数据源正常 */
  sourceError?: string
}>()

/*
 * 离线时整条压暗：这些数字是**上次成功推送**的快照，不是当前真相。
 */
const stale = computed(() => props.status === 'offline')

/*
 * 「快照」旁边必须有「延迟」。只报一个绝对时间戳，用户得自己拿手表减一次；
 * 而大屏最要紧的问题恰恰是「这数字是几秒前的」。-1（从没喂过数据）单独说，
 * 它和「刚到」是两回事。
 */
const lagText = computed<string>(() => {
  const ms = props.staleMs ?? -1
  // -1 = 这条流一帧都没喂过。此时「快照」显示的是首屏 REST 快照的时间，
  // 不说破就等于让那个时间冒充实时。
  if (ms < 0) return '未取到实时数据'
  const seconds = Math.round(ms / 1000)
  return seconds < 60 ? `${seconds}s 前` : `${Math.round(seconds / 60)}min 前`
})

const STATUS_TEXT: Record<ConnectionStatus, string> = {
  connecting: '连接中',
  connected: '已连接',
  reconnecting: '重连中',
  offline: '离线',
}
</script>

<template>
  <footer class="statusbar" :class="{ 'statusbar--stale': stale }">
    <div class="statusbar__left">
      <span class="statusbar__item">
        <span class="statusbar__k">源</span>
        <span class="statusbar__v">{{ source || 'SSE' }}</span>
      </span>
      <span class="statusbar__sep" aria-hidden="true">·</span>
      <span class="statusbar__item">
        <span class="statusbar__k">链路</span>
        <span class="statusbar__v">{{ STATUS_TEXT[status] }}</span>
      </span>
      <span class="statusbar__sep" aria-hidden="true">·</span>
      <span class="statusbar__item">
        <span class="statusbar__k">标的</span>
        <span class="statusbar__v live-num">{{ compactNumber(quoteCount) }}</span>
      </span>
      <span class="statusbar__sep" aria-hidden="true">·</span>
      <span class="statusbar__item">
        <span class="statusbar__k">信号</span>
        <span class="statusbar__v live-num">{{ compactNumber(signalCount) }}</span>
      </span>
      <template v-if="asOf">
        <span class="statusbar__sep" aria-hidden="true">·</span>
        <span class="statusbar__item">
          <span class="statusbar__k">快照</span>
          <span class="statusbar__v live-num">{{ asOf }}</span>
        </span>
      </template>
      <template v-if="lagText">
        <span class="statusbar__sep" aria-hidden="true">·</span>
        <span class="statusbar__item">
          <span class="statusbar__k">延迟</span>
          <span class="statusbar__v live-num">{{ lagText }}</span>
        </span>
      </template>
      <template v-if="sourceError">
        <span class="statusbar__sep" aria-hidden="true">·</span>
        <el-tooltip placement="top" :content="sourceError">
          <span class="statusbar__item statusbar__item--warn" tabindex="0">
            <span class="statusbar__k">数据源</span>
            <span class="statusbar__v">取数失败</span>
          </span>
        </el-tooltip>
      </template>
    </div>

    <el-tooltip
      placement="top-end"
      content="盘中信号与异动归因未定稿，仅供量化决策参考，不构成投资建议"
    >
      <span class="statusbar__note" tabindex="0">信号未定稿·仅供参考</span>
    </el-tooltip>
  </footer>
</template>

<style scoped>
.statusbar {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-3);
  height: var(--live-status-h);
  padding: 0 var(--gap-3);
  background-color: var(--live-head);
  border-top: 1px solid var(--live-rule);
  font-size: var(--fs-kicker);
  color: var(--live-dim);
}

.statusbar--stale {
  opacity: 0.6;
}

.statusbar__left {
  display: flex;
  align-items: center;
  gap: var(--gap-1);
  min-width: 0;
  overflow: hidden;
}

.statusbar__item {
  display: flex;
  align-items: baseline;
  gap: 3px;
  white-space: nowrap;
}

.statusbar__k {
  color: var(--live-dim);
}

/* 数据源故障是运维告警，不是价格涨跌：用告警色，不用红（D1） */
.statusbar__item--warn .statusbar__k,
.statusbar__item--warn .statusbar__v {
  color: var(--live-warn);
  cursor: help;
}

.statusbar__v {
  color: var(--live-muted);
  font-weight: 600;
}

/* 分隔点是字形不是线：边框令牌为 1px 线校准，印成「·」会淡到看不见 */
.statusbar__sep {
  color: var(--text-disabled);
}

/* 合规声明：非价格语义，绝不用红 */
.statusbar__note {
  color: var(--live-dim);
  white-space: nowrap;
  cursor: help;
}

.statusbar__note:focus-visible {
  outline: 1px solid var(--live-accent);
  outline-offset: 1px;
}

@media (max-width: 960px) {
  .statusbar__note {
    display: none;
  }
}
</style>
