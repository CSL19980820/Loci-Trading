<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { auditStrategy, getDecay, getMarketHealth, getOverlap, getStrategies } from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'

const activeTab = ref('health')
const busy = ref(false)
const error = ref('')
const health = ref<Record<string, any> | null>(null)
const decay = ref<Record<string, any>[]>([])
const overlap = ref<Record<string, any>[]>([])
const audits = ref<Record<string, Record<string, any>>>({})
const strategies = ref<{ slug: string; name: string; entry_timing: string }[]>([])
const decayWindow = ref(20)
const overlapDays = ref(60)

const hasInitialData = computed(
  () =>
    health.value != null ||
    decay.value.length > 0 ||
    overlap.value.length > 0 ||
    strategies.value.length > 0,
)

function decayRowClass({ row }: { row: Record<string, any> }): string {
  if (row.signal === 'critical') return 'row-critical'
  if (row.signal === 'warning') return 'row-warning'
  return ''
}

function overlapRowClass({ row }: { row: Record<string, any> }): string {
  if (row.overlap_level === 'high') return 'row-critical'
  if (row.overlap_level === 'medium') return 'row-warning'
  return ''
}

async function safe(task: () => Promise<void>): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    await task()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '请求失败'
  } finally {
    busy.value = false
  }
}

async function loadDecay(): Promise<void> {
  await safe(async () => {
    decay.value = await getDecay({ window: decayWindow.value })
  })
}

async function loadOverlap(): Promise<void> {
  await safe(async () => {
    overlap.value = await getOverlap(overlapDays.value)
  })
}

async function runAudit(slug: string): Promise<void> {
  await safe(async () => {
    const result = await auditStrategy(slug)
    audits.value = { ...audits.value, [slug]: result }
  })
}

async function reload(): Promise<void> {
  await safe(async () => {
    const results = await Promise.allSettled([
      getMarketHealth(),
      getDecay({ window: decayWindow.value }),
      getOverlap(overlapDays.value),
      getStrategies(),
    ])
    const [h, d, o, s] = results
    if (h.status === 'fulfilled') health.value = h.value
    if (d.status === 'fulfilled') decay.value = d.value
    if (o.status === 'fulfilled') overlap.value = o.value
    if (s.status === 'fulfilled') strategies.value = s.value
    const failed = results.filter((r) => r.status === 'rejected') as PromiseRejectedResult[]
    if (failed.length) {
      const msg = failed.map((r) => (r.reason instanceof Error ? r.reason.message : String(r.reason))).join('；')
      error.value = failed.length === results.length ? msg : `部分加载失败：${msg}`
    }
  })
}

onMounted(reload)
</script>

<template>
  <div class="page-fill">
  <PageHeader title="体检" subtitle="数据 · 衰减 · 重叠 · 前视审计">
    <el-button :disabled="busy" @click="reload">刷新全部</el-button>
  </PageHeader>

  <el-alert v-if="error" :title="error" type="error" show-icon closable class="mb" @close="error = ''" />

  <div class="page-scroll page-scroll--busy">
  <PageBusy overlay :busy="busy && !hasInitialData" />
  <el-tabs v-model="activeTab">
    <el-tab-pane label="数据体检" name="health">
      <Sheet title="数据体检">
        <template #actions>
          <span v-if="health" class="chip" :class="health.blocked ? 'chip-red' : 'chip-green'">
            {{ health.blocked ? `${health.block_count} 项阻断` : `通过（${health.warn_count} 项提示）` }}
          </span>
        </template>
        <template v-if="health">
          <p :class="health.blocked ? 'form-error' : 'form-hint'">{{ health.reason }}</p>
          <div v-if="health.findings?.length" class="finding-list">
            <div
              v-for="f in health.findings"
              :key="f.check"
              class="finding-row"
              :class="`finding-${f.severity}`"
            >
              <span class="finding-badge">{{ f.severity }}</span>
              <span>{{ f.message }}</span>
            </div>
          </div>
        </template>
        <PageBusy v-else-if="busy" label="正在体检…" />
        <EmptyState v-else description="点「刷新全部」加载体检结果" :image-size="56" />
      </Sheet>
    </el-tab-pane>

    <el-tab-pane label="策略衰减" name="decay">
      <Sheet title="策略衰减监测">
        <template #actions>
          <span class="inline-label">近</span>
          <el-input-number v-model="decayWindow" :min="5" :max="100" size="small" />
          <span class="inline-label">笔</span>
          <el-button size="small" :disabled="busy" @click="loadDecay">查询</el-button>
        </template>
        <el-table v-if="decay.length" :data="decay" size="small" :row-class-name="decayRowClass">
          <el-table-column label="战法" prop="strategy_tag" min-width="120" />
          <el-table-column label="历史胜率" align="right" width="110">
            <template #default="{ row }">
              {{ row.baseline_win_rate != null ? row.baseline_win_rate.toFixed(1) + '%' : '—' }}
            </template>
          </el-table-column>
          <el-table-column label="近期胜率" align="right" width="110">
            <template #default="{ row }">
              {{ row.recent_win_rate != null ? row.recent_win_rate.toFixed(1) + '%' : '—' }}
            </template>
          </el-table-column>
          <el-table-column label="信号" align="right" width="100">
            <template #default="{ row }">
              <span
                class="chip"
                :class="row.signal === 'critical' ? 'chip-red' : row.signal === 'warning' ? 'chip-yellow' : 'chip-green'"
              >
                {{ ({ ok: '正常', warning: '注意', critical: '衰减' } as Record<string, string>)[String(row.signal)] ?? row.signal }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="样本" align="right" width="100">
            <template #default="{ row }">
              <span class="dim">{{ row.recent_count }}/{{ row.baseline_count }}</span>
            </template>
          </el-table-column>
        </el-table>
        <EmptyState v-else description="无数据（需要有收益字段的复盘记录）" />
      </Sheet>
    </el-tab-pane>

    <el-tab-pane label="战法重叠" name="overlap">
      <Sheet title="战法重叠度">
        <template #actions>
          <span class="inline-label">近</span>
          <el-input-number v-model="overlapDays" :min="10" :max="250" size="small" />
          <span class="inline-label">交易日</span>
          <el-button size="small" :disabled="busy" @click="loadOverlap">查询</el-button>
        </template>
        <el-table v-if="overlap.length" :data="overlap" size="small" :row-class-name="overlapRowClass">
          <el-table-column label="战法 A" prop="strategy_a" min-width="100" />
          <el-table-column label="战法 B" prop="strategy_b" min-width="100" />
          <el-table-column label="平均重叠" align="right" width="110">
            <template #default="{ row }">{{ (row.avg_jaccard * 100).toFixed(1) }}%</template>
          </el-table-column>
          <el-table-column label="比较天数" align="right" width="100" prop="days_compared" />
          <el-table-column label="程度" align="right" width="90">
            <template #default="{ row }">
              <span
                class="chip"
                :class="row.overlap_level === 'high' ? 'chip-red' : row.overlap_level === 'medium' ? 'chip-yellow' : 'chip-green'"
              >
                {{ ({ low: '低', medium: '中', high: '高' } as Record<string, string>)[String(row.overlap_level)] ?? row.overlap_level }}
              </span>
            </template>
          </el-table-column>
        </el-table>
        <EmptyState v-else description="无数据（需要有候选记录）" />
        <p v-if="overlap.some((o) => o.overlap_level === 'high')" class="form-hint form-error">
          高重叠战法持仓高度相关，建议合并或差异化参数。
        </p>
      </Sheet>
    </el-tab-pane>

    <el-tab-pane label="前视审计" name="audit">
      <Sheet title="前视偏差审计">
        <div v-if="strategies.length" class="audit-grid">
          <div v-for="s in strategies" :key="s.slug" class="audit-card">
            <div class="audit-card-head">
              <strong>{{ s.name }}</strong>
              <span class="dim tiny">{{ s.entry_timing }}</span>
            </div>
            <div v-if="!audits[s.slug]">
              <el-button text type="primary" @click="runAudit(s.slug)">运行审计</el-button>
            </div>
            <div v-else>
              <span class="chip" :class="audits[s.slug].failed ? 'chip-red' : 'chip-green'">
                {{ audits[s.slug].failed ? '发现问题' : '通过' }}
              </span>
              <p v-if="audits[s.slug].findings?.length" class="audit-findings">
                {{ audits[s.slug].findings.map((f: { message: string }) => f.message).join('；') }}
              </p>
            </div>
          </div>
        </div>
        <EmptyState v-else description="无战法注册" />
      </Sheet>
    </el-tab-pane>
  </el-tabs>
  </div>
  </div>
</template>

<style scoped>
.mb {
  margin-bottom: 0.85rem;
}
.page-scroll--busy {
  position: relative;
  min-height: 12rem;
}
.finding-list {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  margin-top: 0.65rem;
  padding: 0.15rem 0.25rem 0.5rem;
}
.finding-row {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.65rem;
  align-items: start;
  padding: 0.55rem 0.65rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--sheet) 88%, #fff);
  font-size: 0.86rem;
  line-height: 1.45;
}
.finding-block {
  border-color: color-mix(in srgb, var(--seal) 28%, var(--rule));
  background: color-mix(in srgb, var(--seal-soft) 40%, var(--sheet));
}
.finding-warn {
  border-color: color-mix(in srgb, #c8a400 30%, var(--rule));
}
.finding-badge {
  font-size: 0.68rem;
  padding: 0.12rem 0.4rem;
  border-radius: 3px;
  font-weight: 650;
  letter-spacing: 0.04em;
  flex-shrink: 0;
  background: var(--mist);
  color: #fff;
  text-transform: uppercase;
}
.finding-block .finding-badge {
  background: var(--seal);
}
.finding-warn .finding-badge {
  background: #c8a400;
}
.chip-red {
  background: var(--seal) !important;
  color: #fff !important;
}
.chip-green {
  background: var(--lake) !important;
  color: #fff !important;
}
.chip-yellow {
  background: #c8a400 !important;
  color: #fff !important;
}
.inline-label {
  font-size: 0.82rem;
  color: var(--mist);
}
.audit-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
  gap: 0.65rem;
}
.audit-card {
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  padding: 0.75rem 0.85rem;
  background: var(--sheet);
}
.audit-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.4rem;
}
.tiny {
  font-size: 0.7rem;
}
.audit-findings {
  margin: 0.35rem 0 0;
  font-size: 0.78rem;
  color: var(--mist);
  line-height: 1.45;
}
:deep(.row-critical) {
  background: rgba(196, 30, 58, 0.05);
}
:deep(.row-warning) {
  background: rgba(200, 164, 0, 0.06);
}
</style>
