<script setup lang="ts">
import { Activity, Info, OctagonPause, X } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'

/**
 * 跑道横幅：并行跑着的其它战法、并发到顶、放弃后的残影。
 *
 * 单独成组件是因为这几条都在讲同一件事——「这次选股停不停得掉、别的战法还能
 * 不能开」——文案必须一起改；散在 View 的模板里迟早有人只改其中一条，剩下的
 * 继续说谎。
 *
 * 呈现上收成一条条 32px 高的「状态条」：一枚图标 + 一句话 + 行内入口；解释一律
 * 进 tooltip，悬停可读，不占版面（AGENTS.md 禁常驻说明条）。
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
  <div
    v-if="capacityNotice || parallelRuns.length || abandonedPercent !== null || skillAbandoned"
    class="run-banners"
  >
    <Tooltip v-if="capacityNotice">
      <TooltipTrigger as-child>
        <div class="run-banner run-banner--warn" role="status" tabindex="0">
          <OctagonPause aria-hidden="true" />
          <span class="run-banner__text">{{ capacityNotice }}</span>
        </div>
      </TooltipTrigger>
      <TooltipContent side="bottom" align="start">
        多个战法可以并行选股，但同时在跑的数量有上限：那是为了不把 CPU 摊薄成集体变慢，不是「引擎被独占」
      </TooltipContent>
    </Tooltip>

    <div v-if="parallelRuns.length" class="run-banner run-banner--info" role="status">
      <Activity aria-hidden="true" />
      <Tooltip>
        <TooltipTrigger as-child>
          <span class="run-banner__text" tabindex="0">另外 {{ parallelRuns.length }} 个战法正在并行选股</span>
        </TooltipTrigger>
        <TooltipContent side="bottom" align="start">它们各跑各的，不影响这一个战法开跑</TooltipContent>
      </Tooltip>
      <div class="run-banner__runs">
        <span v-for="run in parallelRuns" :key="run.slug" class="run-banner__run" :title="run.detail">
          <span class="run-banner__name">{{ run.label }}</span>
          <span class="run-banner__pct">{{ run.percent }}%</span>
          <Button access="read" variant="link" size="xs" class="h-auto px-1" @click="emit('focus-run', run.slug)">看进度</Button>
          <Button variant="link" size="xs" class="h-auto px-1 text-warn-ink" @click="emit('abandon-run', run.slug)">停止</Button>
        </span>
      </div>
    </div>

    <div v-if="abandonedPercent !== null" class="run-banner run-banner--warn" role="status">
      <Info aria-hidden="true" />
      <Tooltip>
        <TooltipTrigger as-child>
          <span class="run-banner__text" tabindex="0">
            {{ abandonedStopping ? '已请求停止 · 当前交易日跑完后结束' : '已停止跟踪 · 该次选股仍在后台继续' }}
            （放弃时 {{ abandonedPercent }}%）
          </span>
        </TooltipTrigger>
        <TooltipContent side="bottom" align="start">
          {{
          abandonedStopping
          ? '正在跑的这一个交易日会先跑完并照常入库，之后不再继续；已入库的候选不会撤销'
          : '没能通知到后端，它会跑完并照常入库。别的战法不受影响，照样可以开'
          }}
        </TooltipContent>
      </Tooltip>
      <Button access="read" variant="ghost" size="icon-xs" class="ml-auto" aria-label="关闭提示" @click="emit('dismiss-abandoned')">
        <X aria-hidden="true" />
      </Button>
    </div>

    <div v-if="skillAbandoned" class="run-banner run-banner--warn" role="status">
      <Info aria-hidden="true" />
      <span class="run-banner__text">已停止跟踪 · 该次技能仍在后台继续</span>
    </div>
  </div>
</template>

<style scoped>
.run-banners {
  display: flex;
  flex-shrink: 0;
  flex-direction: column;
  gap: var(--gap-2);
  margin-bottom: var(--gap-3);
}

.run-banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2) var(--gap-3);
  min-height: 32px;
  padding: 5px var(--gap-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: var(--fs-aux);
}

.run-banner > svg {
  flex-shrink: 0;
  width: 14px;
  height: 14px;
}

.run-banner--warn {
  border-color: color-mix(in oklab, var(--warn) 35%, var(--border-subtle));
  background: var(--warn-soft);
  color: var(--warn-ink);
}

.run-banner--info {
  border-color: color-mix(in oklab, var(--info) 35%, var(--border-subtle));
  background: var(--info-soft);
  color: var(--info-ink);
}

.run-banner__text {
  min-width: 0;
  font-weight: 500;
}

.run-banner__runs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-1) var(--gap-3);
}

/* 一个并行战法一枚小条：名字 · 百分比 · 两个入口 */
.run-banner__run {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.run-banner__name {
  color: var(--text-primary);
}

.run-banner__pct {
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}
</style>
