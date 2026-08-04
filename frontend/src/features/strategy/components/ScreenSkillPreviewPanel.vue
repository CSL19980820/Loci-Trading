<script setup lang="ts">
import { computed } from 'vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import type { Pick, ScreenSkillPreviewResponse } from '@/shared/types/quant'

const props = defineProps<{
  preview: ScreenSkillPreviewResponse | null
  previewBusy?: boolean
  saveBusy?: boolean
  tradeDate: string
  codesText: string
}>()

const emit = defineEmits<{
  'update:tradeDate': [value: string]
  'update:codesText': [value: string]
  compile: []
  run: []
  save: []
}>()

const pickColumns: BasicTableColumn[] = [
  { prop: 'code', label: '代码', width: 110 },
  { prop: 'name', label: '名称', minWidth: 120 },
  { prop: 'board_label', label: '板块', width: 96 },
  { prop: 'factors', label: '因子', minWidth: 280, slotName: 'factors' },
]

const pickRows = computed(
  () => (props.preview?.run_result?.picks ?? []) as unknown as Record<string, unknown>[],
)

function factorText(factors: Pick['factors']): string {
  const entries = Object.entries(factors ?? {})
  if (!entries.length) return '—'
  return entries
    .slice(0, 6)
    .map(([key, value]) => `${key}=${value == null ? 'null' : String(value)}`)
    .join(' · ')
}
</script>

<template>
  <div class="workbench-side">
    <Sheet title="编译与试跑" padded margin>
      <div class="sheet-actions-line">
        <el-button type="primary" :loading="previewBusy" @click="emit('compile')">编译校验</el-button>
        <el-button :loading="previewBusy" @click="emit('run')">测试预览</el-button>
        <el-button type="success" :loading="saveBusy" @click="emit('save')">保存战法</el-button>
      </div>
      <div class="preview-grid">
        <el-form-item label="预览日期">
          <el-date-picker
            :model-value="tradeDate"
            type="date"
            value-format="YYYY-MM-DD"
            class="full"
            @update:model-value="emit('update:tradeDate', String($event || ''))"
          />
        </el-form-item>
        <el-form-item label="限定代码">
          <el-input
            :model-value="codesText"
            type="textarea"
            :rows="3"
            placeholder="逗号或换行分隔，例如 600519, 000001"
            @update:model-value="emit('update:codesText', String($event || ''))"
          />
        </el-form-item>
      </div>
    </Sheet>

    <Sheet
      v-if="preview"
      title="诊断与结果"
      :chip="preview.ok ? '已通过' : '待修正'"
      :muted-chip="!preview.ok"
      padded
      margin
    >
      <div v-if="preview.derived" class="derived-grid">
        <div><span class="dim">信号</span><strong>{{ preview.derived.signal }}</strong></div>
        <div><span class="dim">最少 K 线</span><strong>{{ preview.derived.min_bars_required }}</strong></div>
        <div><span class="dim">所需字段</span><strong>{{ preview.derived.required_fields.join(', ') || '—' }}</strong></div>
        <div><span class="dim">因子</span><strong>{{ preview.derived.factors.join(', ') || '—' }}</strong></div>
      </div>
      <ul v-if="preview.diagnostics.length" class="diag-list">
        <li v-for="diag in preview.diagnostics" :key="`${diag.code}-${diag.line}-${diag.column}-${diag.message}`">
          <el-tag
            size="small"
            :type="diag.severity === 'error' ? 'danger' : diag.severity === 'warning' ? 'warning' : 'info'"
            effect="plain"
          >
            {{ diag.code }}
          </el-tag>
          <span class="diag-msg">{{ diag.message }}</span>
          <span v-if="diag.line != null" class="dim mono">L{{ diag.line }}:C{{ diag.column ?? 0 }}</span>
        </li>
      </ul>
      <div v-else class="empty-inline">暂无诊断；可以继续保存或试跑。</div>
    </Sheet>

    <Sheet v-if="preview?.run_result" title="预览命中" :chip="preview.run_result.picks.length" padded>
      <BasicTable
        :columns="pickColumns"
        :data-source="pickRows"
        :pagination="false"
        row-key="code"
        stripe
        empty-text="本次预览无命中"
      >
        <template #factors="{ row }">
          <span class="mono factor-text">{{ factorText((row as unknown as Pick).factors) }}</span>
        </template>
      </BasicTable>
    </Sheet>
    <EmptyState
      v-else-if="!preview"
      description="先编译校验，再决定是否保存；需要时再做小范围试跑。"
      reason="Screen Skill 的保存、更新和删除都依赖最新 revision。"
      eta="建议先用少量代码做 smoke 预览。"
    />
  </div>
</template>

<style scoped>
.workbench-side {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.sheet-actions-line {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.preview-grid,
.derived-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.55rem 0.75rem;
}

.derived-grid {
  margin-bottom: 0.65rem;
}

.derived-grid div {
  display: flex;
  flex-direction: column;
  gap: 0.14rem;
}

.full {
  width: 100%;
}

.mono {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}

.dim {
  color: var(--mist);
  font-size: 0.8rem;
}

.factor-text {
  width: 100%;
}

.diag-list {
  margin: 0;
  padding-left: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.42rem;
}

.diag-msg {
  margin-left: 0.45rem;
  margin-right: 0.45rem;
}

.empty-inline {
  color: var(--mist);
  font-size: 0.86rem;
}

@media (max-width: 640px) {
  .preview-grid,
  .derived-grid {
    grid-template-columns: 1fr;
  }
}
</style>
