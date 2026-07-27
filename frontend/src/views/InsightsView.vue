<template>
  <header class="toolbar">
    <div class="toolbar-title">
      <h1>洞察</h1>
      <span class="muted">策略衰减 · 重叠度 · 数据体检 · 前视审计</span>
    </div>
    <div class="toolbar-actions">
      <button class="quiet-button" :disabled="busy" @click="reload">刷新</button>
    </div>
  </header>

  <p v-if="error" class="error-banner" role="alert"><span>{{ error }}</span></p>

  <!-- 数据体检 -->
  <section class="panel mb">
    <div class="panel-bar">
      <h2>数据体检</h2>
      <span v-if="health" class="chip" :class="health.blocked ? 'chip-red' : 'chip-green'">
        {{ health.blocked ? `${health.block_count} 项阻断` : `通过（${health.warn_count} 项提示）` }}
      </span>
    </div>
    <div v-if="!health" class="muted p8">加载中…</div>
    <div v-else>
      <p v-if="health.blocked" class="form-error">{{ health.reason }}</p>
      <p v-else class="form-hint">{{ health.reason }}</p>
      <div v-if="health.findings?.length" class="finding-list">
        <div v-for="f in health.findings" :key="f.check"
             class="finding-row" :class="`finding-${f.severity}`">
          <span class="finding-badge">{{ f.severity }}</span>
          <span>{{ f.message }}</span>
        </div>
      </div>
    </div>
  </section>

  <!-- 策略衰减 -->
  <section class="panel mb">
    <div class="panel-bar">
      <h2>策略衰减监测</h2>
      <div class="toolbar-actions">
        <label class="inline-label">近 <input v-model.number="decayWindow" type="number" min="5" max="100" style="width:50px"> 笔</label>
        <button class="quiet-button" :disabled="busy" @click="loadDecay">查询</button>
      </div>
    </div>
    <div v-if="!decay.length" class="muted p8">无数据（需要有 return_pct 的复盘记录）</div>
    <div v-else class="table-wrap">
      <table class="dense">
        <thead>
          <tr><th>战法</th><th class="r">历史胜率</th><th class="r">近期胜率</th><th class="r">信号</th><th class="r">样本</th></tr>
        </thead>
        <tbody>
          <tr v-for="d in decay" :key="d.strategy_tag"
              :class="d.signal === 'critical' ? 'row-critical' : d.signal === 'warning' ? 'row-warning' : ''">
            <td>{{ d.strategy_tag }}</td>
            <td class="r">{{ d.baseline_win_rate != null ? d.baseline_win_rate.toFixed(1) + '%' : '—' }}</td>
            <td class="r">{{ d.recent_win_rate != null ? d.recent_win_rate.toFixed(1) + '%' : '—' }}</td>
            <td class="r">
              <span class="chip" :class="d.signal === 'critical' ? 'chip-red' : d.signal === 'warning' ? 'chip-yellow' : 'chip-green'">
              {{ ({ ok: '正常', warning: '注意', critical: '衰减' } as Record<string, string>)[String(d.signal)] ?? d.signal }}
              </span>
            </td>
            <td class="r dim">{{ d.recent_count }}/{{ d.baseline_count }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>

  <!-- 战法重叠度 -->
  <section class="panel mb">
    <div class="panel-bar">
      <h2>战法重叠度</h2>
      <div class="toolbar-actions">
        <label class="inline-label">近 <input v-model.number="overlapDays" type="number" min="10" max="250" style="width:60px"> 交易日</label>
        <button class="quiet-button" :disabled="busy" @click="loadOverlap">查询</button>
      </div>
    </div>
    <div v-if="!overlap.length" class="muted p8">无数据（需要有 core 候选记录）</div>
    <div v-else class="table-wrap">
      <table class="dense">
        <thead>
          <tr><th>战法 A</th><th>战法 B</th><th class="r">平均重叠</th><th class="r">比较天数</th><th class="r">程度</th></tr>
        </thead>
        <tbody>
          <tr v-for="o in overlap" :key="`${o.strategy_a}-${o.strategy_b}`"
              :class="o.overlap_level === 'high' ? 'row-critical' : o.overlap_level === 'medium' ? 'row-warning' : ''">
            <td>{{ o.strategy_a }}</td>
            <td>{{ o.strategy_b }}</td>
            <td class="r">{{ (o.avg_jaccard * 100).toFixed(1) }}%</td>
            <td class="r dim">{{ o.days_compared }}</td>
            <td class="r">
              <span class="chip" :class="o.overlap_level === 'high' ? 'chip-red' : o.overlap_level === 'medium' ? 'chip-yellow' : 'chip-green'">
                {{ ({ low: '低', medium: '中', high: '高' } as Record<string, string>)[String(o.overlap_level)] ?? o.overlap_level }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="overlap.some(o => o.overlap_level === 'high')" class="form-hint" style="color:var(--neg)">
        ⚠ 高重叠战法之间持仓高度相关，形成隐性集中。建议合并或差异化参数。
      </p>
    </div>
  </section>

  <!-- 前视审计 -->
  <section class="panel mb">
    <div class="panel-bar">
      <h2>前视偏差审计</h2>
    </div>
    <div class="audit-grid">
      <div v-for="s in strategies" :key="s.slug" class="audit-card">
        <div class="audit-card-head">
          <strong>{{ s.name }}</strong>
          <span class="dim" style="font-size:11px">{{ s.entry_timing }}</span>
        </div>
        <div v-if="!audits[s.slug]" class="dim" style="font-size:12px">
          <button class="text-link" @click="runAudit(s.slug)">运行审计</button>
        </div>
        <div v-else>
          <span class="chip" :class="audits[s.slug].failed ? 'chip-red' : 'chip-green'">
            {{ audits[s.slug].failed ? '发现问题' : '通过' }}
          </span>
          <p v-if="audits[s.slug].findings?.length" style="font-size:12px;margin:4px 0 0;color:var(--muted)">
            {{ audits[s.slug].findings.map((f: any) => f.message).join('；') }}
          </p>
        </div>
      </div>
    </div>
    <p v-if="!strategies.length" class="muted p8">无战法注册</p>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { auditStrategy, getDecay, getMarketHealth, getOverlap, getStrategies } from '@/api/quant'

const busy = ref(false)
const error = ref('')
const health = ref<Record<string, any> | null>(null)
const decay = ref<Record<string, any>[]>([])
const overlap = ref<Record<string, any>[]>([])
const audits = ref<Record<string, Record<string, any>>>({})
const strategies = ref<{ slug: string; name: string; entry_timing: string }[]>([])
const decayWindow = ref(20)
const overlapDays = ref(60)

async function safe(task: () => Promise<void>): Promise<void> {
  busy.value = true
  error.value = ''
  try { await task() } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '请求失败'
  } finally { busy.value = false }
}

async function loadDecay(): Promise<void> {
  await safe(async () => { decay.value = await getDecay({ window: decayWindow.value }) })
}

async function loadOverlap(): Promise<void> {
  await safe(async () => { overlap.value = await getOverlap(overlapDays.value) })
}

async function runAudit(slug: string): Promise<void> {
  await safe(async () => {
    const result = await auditStrategy(slug)
    audits.value = { ...audits.value, [slug]: result }
  })
}

async function reload(): Promise<void> {
  await safe(async () => {
    const [h, d, o, s] = await Promise.all([
      getMarketHealth(),
      getDecay({ window: decayWindow.value }),
      getOverlap(overlapDays.value),
      getStrategies(),
    ])
    health.value = h
    decay.value = d
    overlap.value = o
    strategies.value = s
  })
}

onMounted(reload)
</script>

<style scoped>
.p8 { padding: 8px 0; }
.finding-list { display: flex; flex-direction: column; gap: 4px; margin-top: 8px; }
.finding-row { display: flex; gap: 8px; align-items: baseline; font-size: 13px; }
.finding-badge { font-size: 11px; padding: 1px 5px; border-radius: 4px; font-weight: 600; flex-shrink: 0; }
.finding-block .finding-badge { background: var(--neg); color: #fff; }
.finding-warn .finding-badge { background: #c8a400; color: #fff; }
.chip-red { background: var(--neg); color: #fff; }
.chip-green { background: var(--pos); color: #fff; }
.chip-yellow { background: #c8a400; color: #fff; }
.row-critical { background: rgba(220, 38, 38, 0.06); }
.row-warning { background: rgba(200, 164, 0, 0.07); }
.inline-label { font-size: 13px; display: flex; align-items: center; gap: 4px; }
.inline-label input { border: 1px solid var(--line-2); border-radius: 4px; padding: 2px 4px; }
.audit-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; padding: 4px 0; }
.audit-card { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; }
.audit-card-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
</style>
