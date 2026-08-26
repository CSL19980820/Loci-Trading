<script setup lang="ts">
import { computed } from 'vue'

import type {
  ScreenSkillLogic,
  ScreenSkillPreviewResponse,
  ScreenSkillReference,
} from '@/shared/types/quant'

const props = defineProps<{
  preview: ScreenSkillPreviewResponse | null
}>()

interface LogicCitation {
  id: string
  reference: ScreenSkillReference | null
}

interface LogicSource {
  logic: ScreenSkillLogic
  citations: LogicCitation[]
}

const logicSources = computed<LogicSource[]>(() => {
  const references = new Map((props.preview?.references ?? []).map((item) => [item.id, item]))
  return (props.preview?.logic ?? []).map((logic) => ({
    logic,
    citations: logic.citations.map((id) => ({ id, reference: references.get(id) ?? null })),
  }))
})

function referenceLocator(reference: ScreenSkillReference | null): string {
  if (!reference) return '引用未解析'
  return [reference.url, reference.path, reference.section]
    .map((item) => String(item ?? '').trim())
    .filter(Boolean)
    .join(' · ') || '未提供定位'
}

function stepKindLabel(kind: string): string {
  if (kind === 'signal') return '主信号'
  if (kind === 'factor') return '因子'
  if (kind === 'intermediate') return '中间量'
  return kind
}

function diagnosticType(severity: string): 'danger' | 'warning' | 'info' {
  if (severity === 'error') return 'danger'
  if (severity === 'warning') return 'warning'
  return 'info'
}
</script>

<template>
  <section class="report" aria-label="策略测试解释">
    <div class="report__head">
      <div>
        <span class="report__eyebrow">编译与试跑</span>
        <strong>中文策略脉络</strong>
      </div>
      <el-tag v-if="preview" size="small" :type="preview.ok ? 'success' : 'danger'" effect="plain">
        {{ preview.ok ? '已通过' : '待修正' }}
      </el-tag>
    </div>

    <el-empty v-if="!preview" :image-size="48" description="编译后在这里查看策略解释与诊断。" />

    <template v-else>
      <div v-if="preview.explanation" class="report__content">
        <p class="report__summary">{{ preview.explanation.summary }}</p>
        <ol class="report__steps">
          <li v-for="step in preview.explanation.steps" :key="step.id" class="report__step">
            <div class="report__step-head">
              <strong>{{ step.title }}</strong>
              <span>{{ stepKindLabel(step.kind) }}<template v-if="step.line != null"> · L{{ step.line }}</template></span>
            </div>
            <code>{{ step.expression }}</code>
            <p>{{ step.plain_text }}</p>
            <div class="report__tokens">
              <el-tag v-for="field in step.fields" :key="`field-${step.id}-${field}`" size="small" effect="plain">{{ field }}</el-tag>
              <el-tag v-for="fn in step.functions" :key="`function-${step.id}-${fn}`" size="small" type="info" effect="plain">{{ fn }}</el-tag>
            </div>
          </li>
        </ol>

        <div class="report__data" aria-label="数据要求">
          <span>字段：{{ preview.explanation.data_requirements.fields.join(', ') || '未声明' }}</span>
          <span>最少 K 线：{{ preview.explanation.data_requirements.min_bars }}</span>
          <span>复权：{{ preview.explanation.data_requirements.adjust }}</span>
          <span>股票池：{{ preview.explanation.data_requirements.universe ? '已声明' : '未声明' }}</span>
          <span>时点：{{ preview.explanation.timing.plain_text }}</span>
        </div>
      </div>
      <el-alert v-else title="本次预览未返回中文策略解释。" type="info" :closable="false" show-icon />

      <section v-if="logicSources.length" class="report__sources" aria-label="逻辑资料来源">
        <div class="report__sources-head">
          <strong>逻辑资料来源</strong>
          <span>{{ logicSources.length }} 条逻辑</span>
        </div>
        <article v-for="row in logicSources" :key="row.logic.id" class="report__logic-source">
          <div class="report__logic-head">
            <strong>{{ row.logic.title }}</strong>
            <code>{{ row.logic.id }}</code>
          </div>
          <div v-if="row.citations.length" class="report__citation-list">
            <div v-for="citation in row.citations" :key="`${row.logic.id}-${citation.id}`" class="report__citation">
              <div class="report__citation-head">
                <strong>{{ citation.reference?.title || citation.id }}</strong>
                <span>{{ citation.id }}<template v-if="citation.reference?.kind"> · {{ citation.reference.kind }}</template></span>
              </div>
              <code class="report__locator">{{ referenceLocator(citation.reference) }}</code>
              <blockquote v-if="citation.reference?.quote">{{ citation.reference.quote }}</blockquote>
            </div>
          </div>
          <el-alert v-else title="这条逻辑尚未关联资料来源。" type="warning" :closable="false" show-icon />
        </article>
      </section>

      <div v-if="preview.diagnostics.length" class="report__diagnostics" aria-label="编译诊断">
        <div v-for="diag in preview.diagnostics" :key="`${diag.code}-${diag.line}-${diag.column}-${diag.message}`" class="report__diagnostic">
          <el-tag size="small" :type="diagnosticType(diag.severity)" effect="plain">{{ diag.code }}</el-tag>
          <span>{{ diag.message }}</span>
          <small v-if="diag.line != null">L{{ diag.line }}:C{{ diag.column ?? 0 }}</small>
        </div>
      </div>

      <div v-if="preview.run_result" class="report__hits" aria-label="试跑命中摘要">
        <strong>
          试跑正式 {{ preview.run_result.picks.length }} 只 · 低吸观察
          {{ preview.run_result.watch_picks?.length ?? 0 }} 只
        </strong>
        <span>{{ preview.run_result.trade_date }} · 股票池 {{ preview.run_result.universe_size }} · {{ preview.run_result.elapsed_seconds.toFixed(2) }}s</span>
      </div>
    </template>
  </section>
</template>

<style scoped>
.report { display: flex; flex-direction: column; min-width: 0; gap: .65rem; }
.report__head, .report__step-head, .report__hits { display: flex; align-items: flex-start; justify-content: space-between; gap: .65rem; }
.report__head strong { display: block; font-size: .92rem; }
.report__eyebrow { color: var(--mist); font: .72rem/1.25 var(--mono); }
.report__summary { margin: 0; color: var(--muted); font-size: .84rem; }
.report__steps { display: flex; flex-direction: column; gap: .45rem; margin: 0; padding: 0; list-style: none; counter-reset: step; }
.report__step { position: relative; padding: .55rem .6rem .55rem 2rem; border-left: 2px solid var(--seal); background: color-mix(in srgb, var(--sheet) 72%, transparent); counter-increment: step; }
.report__step::before { position: absolute; top: .58rem; left: .55rem; color: var(--seal-ink); content: counter(step); font: 600 .72rem/1.4 var(--mono); }
.report__step-head span, .report__diagnostic small, .report__hits span { color: var(--mist); font: .72rem/1.3 var(--mono); }
.report__step code { display: block; margin-top: .28rem; color: var(--ink); font: .76rem/1.4 var(--mono); overflow-wrap: anywhere; }
.report__step p { margin: .32rem 0; font-size: .8rem; }
.report__tokens { display: flex; flex-wrap: wrap; gap: .25rem; }
.report__sources { display: flex; flex-direction: column; gap: .45rem; padding-top: .55rem; border-top: 1px solid var(--rule); }
.report__sources-head, .report__logic-head, .report__citation-head { display: flex; align-items: baseline; justify-content: space-between; gap: .55rem; }
.report__sources-head span, .report__logic-head code, .report__citation-head span { color: var(--mist); font: .7rem/1.35 var(--mono); }
.report__logic-source { display: flex; flex-direction: column; gap: .35rem; padding-left: .55rem; border-left: 2px solid var(--rule); }
.report__citation-list { display: flex; flex-direction: column; gap: .35rem; }
.report__citation { display: flex; flex-direction: column; gap: .2rem; padding: .4rem .5rem; background: color-mix(in srgb, var(--panel-2) 78%, transparent); }
.report__citation-head strong { font-size: .78rem; }
.report__locator { color: var(--muted); font: .7rem/1.4 var(--mono); overflow-wrap: anywhere; }
.report__citation blockquote { margin: .08rem 0 0; color: var(--muted); font-size: .76rem; line-height: 1.45; }
.report__data { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .35rem .65rem; padding-top: .55rem; border-top: 1px solid var(--rule); color: var(--muted); font-size: .78rem; }
.report__diagnostics { display: flex; flex-direction: column; gap: .35rem; padding-top: .55rem; border-top: 1px solid var(--rule); }
.report__diagnostic { display: flex; align-items: baseline; flex-wrap: wrap; gap: .35rem; font-size: .8rem; }
.report__hits { align-items: baseline; padding-top: .55rem; border-top: 1px solid var(--rule); font-size: .82rem; }
@media (max-width: 640px) { .report__data { grid-template-columns: 1fr; } .report__hits { align-items: flex-start; flex-direction: column; } }
</style>
