<script setup lang="ts">
/**
 * 跑道横幅：并行跑着的其它战法、并发到顶、放弃后的残影。
 *
 * 单独成组件是因为这几条都在讲同一件事——「这次选股停不停得掉、别的战法还能
 * 不能开」——文案必须一起改；散在 View 的模板里迟早有人只改其中一条，剩下的
 * 继续说谎。
 *
 * 历史包袱：这里曾挂着一句「引擎是后端全局单槽：它跑完之前，所有战法的选股都
 * 开不了」。后端进度槽改成「租户 × 战法」双层之后那句话是**假的**，已删除。
 * 现在只有真的撞到并发上限才提示「先停一个或等一个跑完」。
 */
interface ParallelRun {
  slug: string
  label: string
  percent: number
  /** 形如「三源共振 · 已跑 2 分 13 秒 · 42% · 扫描候选」 */
  detail: string
}

defineProps<{
  /** 并行跑着的**其它**战法；不阻塞本页开跑，只是告知 + 给个入口 */
  parallelRuns: ParallelRun[]
  /** 并发到顶的说明；空串 = 没到顶 */
  capacityNotice: string
  /** 本战法放弃跟踪后停在多少百分比；null = 没有残影 */
  abandonedPercent: number | null
  /** 后端是否受理了停止；没受理就只是「前端不看了」 */
  abandonedStopping: boolean
  skillAbandoned: boolean
}>()

const emit = defineEmits<{
  'focus-run': [slug: string]
  'abandon-run': [slug: string]
  'dismiss-abandoned': []
}>()
</script>

<template>
  <!--
    三条横幅都只留「出了什么事」这一句：原来每条底下还挂一段两三行的解释，
    那是常驻说明条，AGENTS.md §3.9 明令禁止（el-alert 不写 description / 长说明）。
    解释一律进 tooltip，悬停可读，不占版面。
  -->
  <el-tooltip
    v-if="capacityNotice"
    placement="bottom-start"
    content="多个战法可以并行选股，但同时在跑的数量有上限：那是为了不把 CPU 摊薄成集体变慢，不是「引擎被独占」"
  >
    <el-alert type="warning" show-icon :closable="false" class="run-banner">
      <template #title>{{ capacityNotice }}</template>
    </el-alert>
  </el-tooltip>

  <el-alert
    v-if="parallelRuns.length"
    type="info"
    show-icon
    :closable="false"
    class="run-banner"
  >
    <template #title>
      <el-tooltip placement="bottom-start" content="它们各跑各的，不影响这一个战法开跑">
        <span>另外 {{ parallelRuns.length }} 个战法正在并行选股</span>
      </el-tooltip>
    </template>
    <div class="run-banner__row">
      <span
        v-for="run in parallelRuns"
        :key="run.slug"
        class="run-banner__run"
        :title="run.detail"
      >
        <span class="run-banner__name">{{ run.label }}</span>
        <span class="run-banner__pct">{{ run.percent }}%</span>
        <el-button link size="small" @click="emit('focus-run', run.slug)">看进度</el-button>
        <el-button link size="small" @click="emit('abandon-run', run.slug)">停止</el-button>
      </span>
    </div>
  </el-alert>

  <el-alert
    v-if="abandonedPercent !== null"
    type="warning"
    show-icon
    class="run-banner"
    @close="emit('dismiss-abandoned')"
  >
    <template #title>
      <el-tooltip
        placement="bottom-start"
        :content="abandonedStopping
          ? '正在跑的这一个交易日会先跑完并照常入库，之后不再继续；已入库的候选不会撤销'
          : '没能通知到后端，它会跑完并照常入库。别的战法不受影响，照样可以开'
        "
      >
        <span>
          {{ abandonedStopping ? '已请求停止 · 当前交易日跑完后结束' : '已停止跟踪 · 该次选股仍在后台继续' }}
          （放弃时 {{ abandonedPercent }}%）
        </span>
      </el-tooltip>
    </template>
  </el-alert>

  <el-alert
    v-if="skillAbandoned"
    type="warning"
    show-icon
    :closable="false"
    class="run-banner"
    title="已停止跟踪 · 该次技能仍在后台继续"
  />
</template>

<style scoped>
.run-banner {
  flex: 0 0 auto;
  margin-bottom: 0.4rem;
}

.run-banner__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem 0.9rem;
}

/* 一个并行战法一枚小条：名字 · 百分比 · 两个入口 */
.run-banner__run {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.78rem;
}

.run-banner__name {
  color: var(--ink);
}

.run-banner__pct {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
  color: var(--mist);
}
</style>
