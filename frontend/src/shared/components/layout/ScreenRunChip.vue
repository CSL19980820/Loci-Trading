<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { strategyLabel } from '@/shared/lib/format'
import { useScreenRunStore } from '@/shared/stores/screenRun'

const store = useScreenRunStore()
const { running, runningStrategies, abandoned } = storeToRefs(store)
const route = useRoute()
const router = useRouter()

/** 轨上只摊开一个战法（最早开跑的那个），其余进「+N」与 tooltip */
const primarySlug = computed(() => runningStrategies.value[0] ?? '')
const strategyName = computed(() => strategyLabel(primarySlug.value))
const primaryPercent = computed(() => store.percentFor(primarySlug.value))
const extraCount = computed(() => Math.max(0, runningStrategies.value.length - 1))
const abandonedName = computed(() => strategyLabel(abandoned.value?.strategy || ''))
/**
 * 选股工作台自带整块进度面板，轨上不重复提示。
 * 改这一条时同步改 App.vue 的 `screenChipActive`，否则会渲染出一条空轨。
 */
const onWorkbench = () => route.name === 'screen-history'

/**
 * 轨上放「选股 · 战法 · 百分比（· +N）」，每个战法的耗时与后端 message 全进 tooltip。
 *
 * 多战法可以真的并行（后端进度槽按「租户 × 战法」分片），所以这里不能再假设
 * 只有一条在跑。
 */
const runTip = computed(() => {
  const rows = runningStrategies.value.map((slug) => store.detailFor(slug)).filter(Boolean)
  if (!rows.length) return '选股进行中'
  return `选股进行中 ｜ ${rows.join(' ｜ ')}`
})

function goProgress(): void {
  void router.push({
    name: 'screen-history',
    query: primarySlug.value ? { select: `engine:${primarySlug.value}` } : undefined,
  })
}

/**
 * 「停止」是协作式的，不是立刻掐断。
 *
 * 后端 `POST /api/screen/run/cancel?strategy=` 只立一面旗，选股线程在**下一个交易
 * 日**的检查点才退出——当前这一日会先跑完并照常入库。所以确认框要把两件事都说
 * 清：会停，但不是马上；已经跑完的不会回滚。
 *
 * 轨上只在**恰好一个**战法在跑时给停止按钮：并行时「停止」指谁全靠猜，工作台
 * 里每条进度旁边都有自己的入口。
 */
async function abandonRun(): Promise<void> {
  const slug = primarySlug.value
  if (!slug) return
  const label = strategyLabel(slug) || slug
  try {
    await ElMessageBox.confirm(
      '正在跑的这一个交易日会先跑完并照常入库，之后不再继续。已经入库的候选不会撤销。',
      `停止「${label}」这次选股？`,
      { confirmButtonText: '停止', cancelButtonText: '继续跑', type: 'warning' },
    )
  } catch {
    return
  }
  await store.abandon(slug)
  ElMessage.info(
    store.abandonedFor(slug)?.stopping
      ? '已请求停止 · 当前交易日跑完后结束'
      : '没能通知到后端 · 这一轮仍会在后台跑完',
  )
}
</script>

<template>
  <el-tooltip v-if="running && !onWorkbench()" :content="runTip" placement="bottom" :show-after="150">
    <div class="run-chip run-chip--busy">
      <span class="run-chip__pulse" aria-hidden="true" />
      <el-button
        link
        native-type="button"
        class="run-chip__act run-chip__act--main"
        :aria-label="`${runTip}，点此查看进度`"
        @click="goProgress"
      >
        <span class="run-chip__text">选股{{ strategyName ? ` ${strategyName}` : '' }}</span>
        <span class="run-chip__num">{{ primaryPercent }}%</span>
        <span v-if="extraCount" class="run-chip__more">+{{ extraCount }}</span>
      </el-button>
      <el-button
        v-if="runningStrategies.length === 1"
        link
        native-type="button"
        class="run-chip__act run-chip__act--mute"
        aria-label="停止这次选股"
        @click="abandonRun"
      >
        停止
      </el-button>
    </div>
  </el-tooltip>

  <div v-else-if="abandoned && !onWorkbench()" class="run-chip run-chip--ghost">
    <span class="run-chip__text">
      选股已放弃<span v-if="abandonedName"> · {{ abandonedName }}</span>
    </span>
    <span class="run-chip__num">{{ abandoned.percent }}%</span>
    <el-button
      link
      native-type="button"
      class="run-chip__act run-chip__act--mute"
      aria-label="不再提示这次放弃的选股"
      @click="store.dismissAbandoned(abandoned.strategy)"
    >
      知道了
    </el-button>
  </div>
</template>

<style scoped>
/* 状态轨上的一枚 chip：20px 高、11px 字、3px 圆角、1px 边——与 App.vue 的 .rail-chip 同尺寸 */
.run-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-1);
  flex: 0 1 auto;
  min-width: 0;
  height: 20px;
  padding: 0 var(--gap-1);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  color: var(--ink);
  font-size: var(--fs-kicker);
  line-height: 1;
  white-space: nowrap;
}

.run-chip--busy {
  border-color: color-mix(in oklab, var(--seal) 35%, var(--rule));
  background: var(--seal-soft);
}

/* 放弃后的残影：虚线框 + 灰字，一眼看出「这不是在跑」，但事儿还没完 */
.run-chip--ghost {
  border-style: dashed;
  color: var(--mist);
}

.run-chip__text {
  overflow: hidden;
  text-overflow: ellipsis;
}

.run-chip__num {
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
}

/* 「+2」：并行跑着的其它战法数量。多槽之后轨上必须放得下不止一个 */
.run-chip__more {
  padding: 0 3px;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  color: var(--mist);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
}

.run-chip__pulse {
  flex-shrink: 0;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--seal);
  animation: run-chip-blink 1.2s ease-in-out infinite;
}

.run-chip__act.el-button {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-1);
  height: auto;
  margin: 0;
  padding: 0;
  border: 0;
  font-size: var(--fs-kicker);
  font-weight: 400;
}

/* EP 把默认插槽包一层 <span>：文案与百分比之间的 gap 要落在那一层上 */
.run-chip__act.el-button > :deep(span) {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-1);
  min-width: 0;
}

.run-chip__act.el-button + .run-chip__act.el-button {
  margin-left: var(--gap-1);
}

.run-chip__act--main.el-button {
  --el-button-text-color: var(--ink);
  --el-button-hover-text-color: var(--seal-ink);
  min-width: 0;
}

.run-chip__act--mute.el-button {
  --el-button-text-color: var(--mist);
  --el-button-hover-text-color: var(--ink);
}

@keyframes run-chip-blink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.3;
  }
}

@media (prefers-reduced-motion: reduce) {
  .run-chip__pulse {
    animation: none;
  }
}
</style>
