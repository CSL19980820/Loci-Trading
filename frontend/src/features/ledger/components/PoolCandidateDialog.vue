<script setup lang="ts">
/**
 * 候选详情弹窗：一条候选的九项事实 + evidence 原文 + 三个动作。
 *
 * 版式（Linear issue 详情一路）：
 *   头部 = 名称（大）+ 代码 + 裁决徽标；右侧评分大数
 *   事实栅格：选出日 / 时点 / 战法 / 池 / 来源（标签在上、值在下）
 *   理由：引用块；证据：折叠面板里的原文
 *   底栏：删除（左）· 关闭 · 看档案（主）
 * 手机端由 DialogContent 自动贴底；事实栅格退成两列。
 *
 * 与列表页只共享「当前选中的那条候选」。战法 / 池 / 来源三处文案由页面解析完再
 * 传进来：弹窗自己不认 slug、不碰战法目录。删除与看档案都往外抛——批次会话与列表刷新归页面管。
 */
import { computed } from 'vue'
import { FileText, Trash2, X } from '@lucide/vue'

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/shared/components/ui/accordion'
import { Button } from '@/shared/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import StockLink from '@/shared/components/ui/StockLink.vue'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { decisionLabel, timingLabel } from '@/shared/lib/format'
import { formatDateTime } from '@/shared/lib/dateTime'
import type { OpenBatchInput } from '@/shared/stores/batchBrowse'
import type { Candidate } from '@/shared/types/palace'

const props = defineProps<{
  candidate: Candidate | null
  /** 战法中文名（页面查目录解析好） */
  strategyText: string
  /** 池号：战法中文名 · 候选日 */
  poolText: string
  /** 写入来源中文名 */
  sourceText: string
  batch: Omit<OpenBatchInput, 'focusCode'> | null
}>()

const emit = defineEmits<{ delete: [row: Candidate]; archive: [] }>()

const open = defineModel<boolean>({ required: true })

const title = computed(() => props.candidate?.name || '候选详情')

const decisionVariant = computed<'info' | 'warn' | 'secondary'>(() => {
  const label = decisionLabel(props.candidate?.decision ?? '')
  if (label === '精选') return 'info'
  if (label === '观察') return 'warn'
  return 'secondary'
})

const facts = computed(() => {
  const c = props.candidate
  if (!c) return []
  return [
    { key: '选出日', value: c.date, mono: true },
    { key: '时点', value: timingLabel(c.timing) },
    { key: '战法', value: props.strategyText },
    { key: '池', value: props.poolText },
    { key: '来源', value: props.sourceText },
    { key: '写入时间', value: formatDateTime(c.created_at), mono: true },
  ]
})

const evidenceText = computed(() => {
  const ev = props.candidate?.evidence
  if (!ev || !Object.keys(ev).length) return ''
  return JSON.stringify(ev, null, 2)
})

const evidenceCount = computed(() => Object.keys(props.candidate?.evidence ?? {}).length)

function fmtScore(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  const n = Number(value)
  return Number.isInteger(n) ? String(n) : n.toFixed(1)
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="pool-detail-dialog gap-0 p-0 sm:max-w-2xl">
      <DialogHeader class="pool-detail__head text-left">
        <div class="pool-detail__id">
          <DialogTitle class="pool-detail__title">
            <template v-if="candidate">
              <StockLink
                :code="candidate.code"
                :name="candidate.name"
                :date="candidate.date"
                :batch="batch"
                :show-code="false"
                class="pool-detail__link"
              />
              <span class="pool-detail__code">{{ candidate.code }}</span>
            </template>
            <template v-else>{{ title }}</template>
          </DialogTitle>
          <DialogDescription v-if="candidate" class="pool-detail__desc">
            <UiBadge :variant="decisionVariant">{{ decisionLabel(candidate.decision) }}</UiBadge>
            <span>{{ strategyText }}</span>
          </DialogDescription>
        </div>
        <div v-if="candidate" class="pool-detail__score" aria-label="评分">
          <span class="pool-detail__score-num">{{ fmtScore(candidate.score) }}</span>
          <span class="pool-detail__score-label">评分</span>
        </div>
      </DialogHeader>

      <div v-if="candidate" class="pool-detail__body">
        <dl class="pool-detail__facts">
          <div v-for="fact in facts" :key="fact.key" class="pool-detail__fact" :class="{ 'pool-detail__fact--wide': fact.key === '写入时间' || fact.key === '池' }">
            <dt>{{ fact.key }}</dt>
            <dd :class="{ 'pool-detail__mono': fact.mono }">{{ fact.value || '—' }}</dd>
          </div>
        </dl>

        <section class="pool-detail__reason" aria-label="理由">
          <h3 class="pool-detail__section-title">理由</h3>
          <p class="pool-detail__reason-text">{{ candidate.reason || '未记录理由' }}</p>
        </section>

        <Accordion v-if="evidenceText" type="single" collapsible class="pool-detail__evidence">
          <AccordionItem value="evidence" class="border-0">
            <AccordionTrigger class="pool-detail__evidence-trigger">
              证据数据
              <span class="pool-detail__evidence-count">{{ evidenceCount }} 项</span>
            </AccordionTrigger>
            <AccordionContent class="pb-0">
              <pre class="pool-detail__pre">{{ evidenceText }}</pre>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>

      <DialogFooter class="pool-detail__foot">
        <Button
          v-if="candidate"
          variant="soft-destructive"
          class="pool-detail__delete"
          @click="emit('delete', candidate)"
        >
          <Trash2 aria-hidden="true" />
          删除
        </Button>
        <Button access="read" variant="outline" @click="open = false">
          <X aria-hidden="true" />
          关闭
        </Button>
        <Button access="read" v-if="candidate" @click="emit('archive')">
          <FileText aria-hidden="true" />
          档案
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<style scoped>
.pool-detail-dialog { display:flex; flex-direction:column; max-height:90dvh; overflow:hidden; }
.pool-detail__head {
  flex-shrink:0;
  display:flex;
  flex-direction: row;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--gap-4);
  padding: var(--gap-5) var(--gap-5) var(--gap-4);
  padding-right: calc(var(--gap-5) + 32px);
  border-bottom: 1px solid var(--border-subtle);
}

.pool-detail__id {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.pool-detail__title {
  display: flex;
  flex-wrap: nowrap;
  align-items: baseline;
  gap: var(--gap-2);
  margin: 0;
  min-width: 0;
  font-size: var(--fs-hero);
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
}

.pool-detail__link {
  color: var(--text-primary);
}

.pool-detail__code {
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-ui);
  font-weight: 500;
  letter-spacing: 0.02em;
}

.pool-detail__desc {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
  margin: 0;
  color: var(--text-secondary);
  font-size: var(--fs-ui);
}

.pool-detail__dot {
  color: var(--text-tertiary);
}

.pool-detail__mono {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}

.pool-detail__score {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  flex-shrink: 0;
  gap: 2px;
}

.pool-detail__score-num {
  font-family: var(--mono);
  font-size: var(--fs-display);
  font-weight: 600;
  letter-spacing: -0.02em;
  line-height: 1;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}

.pool-detail__score-label {
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
}

.pool-detail__body {
  display: flex;
  flex-direction: column;
  gap: var(--gap-4);
  min-width: 0;
  flex:1 1 auto; min-height:0; max-height:none;
  padding: var(--gap-4) var(--gap-5);
  overflow: auto;
  overscroll-behavior: contain;
}

/* 事实栅格：标签在上、值在下，三列 */
.pool-detail__facts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--gap-3) var(--gap-4);
  margin: 0;
}

.pool-detail__fact {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.pool-detail__fact dt {
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
  font-weight: 500;
  letter-spacing: 0.02em;
}

.pool-detail__fact dd {
  margin: 0;
  min-width: 0;
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 500;
  overflow-wrap: anywhere;
}

.pool-detail__section-title {
  margin: 0 0 6px;
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
  font-weight: 500;
  letter-spacing: 0.02em;
}

.pool-detail__reason-text {
  margin: 0;
  padding: var(--gap-3) var(--gap-4);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface-sunken);
  color: var(--text-primary);
  font-size: var(--fs-body);
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.pool-detail__evidence {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  padding: 0 var(--gap-3);
}

.pool-detail__evidence-trigger {
  padding-block: var(--gap-2);
  font-size: var(--fs-ui);
  font-weight: 500;
}

.pool-detail__evidence-count {
  margin-left: auto;
  margin-right: var(--gap-2);
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-weight: 500;
}

.pool-detail__pre {
  margin: 0 0 var(--gap-3);
  padding: var(--gap-3);
  border-radius: var(--radius);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  font: var(--fs-aux) / 1.5 var(--mono);
  max-height: 16rem;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.pool-detail__foot {
  flex-shrink:0;
  display:flex;
  flex-direction: row;
  flex-wrap: nowrap;
  align-items: center;
  justify-content: flex-end;
  gap: var(--gap-2);
  padding: var(--gap-3) var(--gap-5);
  border-top: 1px solid var(--border-subtle);
  background: transparent;
  border-radius: 0 0 var(--radius-xl) var(--radius-xl);
}

.pool-detail__foot > :deep(button) {
  flex: 0 0 auto;
  white-space: nowrap;
}

.pool-detail__delete {
  margin-right: auto;
}

@media (max-width: 640px) {
  .pool-detail__head {
    padding: var(--gap-3) var(--gap-4) var(--gap-3);
    padding-right: calc(var(--gap-4) + 36px);
  }

  .pool-detail__title {
    font-size: var(--fs-title);
  }

  .pool-detail__score-num {
    font-size:20px;
  }

  .pool-detail__body {
    padding: var(--gap-3) var(--gap-4);
    max-height:none;
    overflow:auto;
  }

  .pool-detail__facts { grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
  .pool-detail__fact--wide { grid-column:1/-1; }
  .pool-detail__fact--wide .pool-detail__mono { white-space:nowrap; }
  .pool-detail__title { flex-wrap:wrap; white-space:normal; gap:4px 8px; overflow:visible; }

  .pool-detail__foot {
    padding: var(--gap-3) var(--gap-4);
    border-radius: 0;
    background: transparent;
    flex-wrap: nowrap;
  }

  .pool-detail__foot > :deep(*) {
    flex: 1 1 0;
    min-width: 0;
  }

  .pool-detail__delete {
    margin-right: 0;
  }
}
</style>
