<script setup lang="ts">
import { Search, RefreshRight } from '@element-plus/icons-vue'
/**
 * 审计日志。全站统一的「筛选栏 + BasicTable + 分页」列表骨架。
 *
 * 三条界面纪律（都是旧版踩过的坑）：
 * 1. **必须分页**。旧版一次拉 50 条就到头，第 51 条之后的操作等于不存在——
 * 审计表没有分页就不是审计，是最近动态。
 * 2. **不出机器码**。`action` / `outcome` 一律过字典转中文，
 *    筛选下拉也给中文选项；`admin.set_role` 只允许活在网络层。
 * 3. **详情走弹窗，不走展开行**。展开行里那块 `<pre>` 会把行高撞成两百 px，
 *    展开箭头还白占一整列；右侧一颗「查看」按钮既省列宽也省滚动。
 */
import { computed, ref } from 'vue'

import { listAdminAudit } from '@/shared/api/admin'
import PageContainer from '@/shared/components/layout/PageContainer.vue'
import BasicForm from '@/shared/components/ui/BasicForm.vue'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import type { AuditLogItem } from '@/shared/types/admin'
import {
  ACTION_OPTIONS,
  actionLabel,
  logTime,
  outcomeLabel,
  outcomeTagType,
} from '../lib/adminDict'
import {
  EMPTY_LOG_FILTERS,
  createLogColumns,
  createLogFilterSchemas,
  fetchLogPage,
  formatLogDetail,
  type LogFilters,
} from './logTableParts'

const tableRef = ref<InstanceType<typeof BasicTable>>()
const filters = ref<LogFilters>({ ...EMPTY_LOG_FILTERS })

const detailVisible = ref(false)
const detailRow = ref<AuditLogItem | null>(null)

const filterSchemas = createLogFilterSchemas({
  keywordPlaceholder: '操作人 / 目标对象',
  actionLabel: '操作类型',
  actionOptions: ACTION_OPTIONS,
  outcomeLabel: '执行结果',
  // 操作类型有十几项，不给搜索框就得在下拉里滚着找
  actionFilterable: true,
})

const shared = createLogColumns({
  actorLabel: '操作人',
  actorMinWidth: 130,
  actionLabel: '操作类型',
  actionWidth: 130,
  ipWidth: 130,
})

const columns = ref<BasicTableColumn[]>([
  shared.time,
  shared.actor,
  shared.action,
  {
    prop: 'target',
    label: '目标对象',
    minWidth: 140,
    showOverflowTooltip: true,
    formatter: (row) => (row.target as string) || '—',
  },
  shared.outcome,
  shared.ip,
  {
    prop: 'detail',
    label: '详情',
    width: 88,
    fixed: 'right',
    align: 'center',
    headerAlign: 'center',
    slotName: 'detail',
  },
])

/** 弹窗上半部的「事实格」：六个字段一眼扫完，不必去 JSON 里翻。 */
const detailFacts = computed<{ label: string; value: string }[]>(() => {
  const row = detailRow.value
  if (!row) return []
  return [
    { label: '时间', value: logTime(row.occurred_at) },
    { label: '操作人', value: row.actor_name || '系统' },
    { label: '操作类型', value: actionLabel(row.action) },
    { label: '目标对象', value: row.target || '—' },
    { label: '执行结果', value: outcomeLabel(row.outcome) },
    { label: '来源 IP', value: row.ip || '—' },
  ]
})

const detailText = computed(() => formatLogDetail(detailRow.value?.detail_json))

async function loadAudit(params: {
  currentPage: number
  pageSize: number
}): Promise<{ list: Record<string, unknown>[]; total: number }> {
  return fetchLogPage({
    fetcher: listAdminAudit,
    filters: filters.value,
    params,
    actionMode: 'server',
    errorMessage: '加载审计日志失败',
  })
}

function reload(): void {
  void tableRef.value?.restReload()
}

function onReset(): void {
  filters.value = { ...EMPTY_LOG_FILTERS }
  reload()
}

function openDetail(row: AuditLogItem): void {
  detailRow.value = row
  detailVisible.value = true
}
</script>

<template>
  <div class="admin-pane admin-list">
    <PageContainer>
      <template #search>
        <div class="admin-pane__filters">
          <BasicForm
            v-model="filters"
            :schemas="filterSchemas"
            :columns="3"
            label-position="left"
            label-width="5em"
          />
        </div>
        <div class="admin-pane__filter-actions">
          <el-button type="primary" :icon="Search" @click="reload">查询</el-button>
          <el-button :icon="RefreshRight" @click="onReset">重置</el-button>
        </div>
      </template>

      <template #main>
        <BasicTable
          ref="tableRef"
          v-model:columns="columns"
          :request="loadAudit"
          :pagination="{ pageSize: 20, pageSizes: [20, 50, 100] }"
          :toolbar-config="{ refresh: true, custom: true }"
          height="100%"
          row-key="id"
          stripe
          empty-text="没有匹配的审计记录"
        >
          <template #actor="{ row }">
            <el-tooltip
              v-if="row.actor_id"
              :content="`账号 ID：${row.actor_id}`"
              placement="top"
              :show-after="200"
            >
              <span class="audit-actor">{{ row.actor_name || '系统' }}</span>
            </el-tooltip>
            <span v-else class="audit-actor">{{ row.actor_name || '系统' }}</span>
          </template>

          <template #action="{ row }">
            <el-tag size="small" type="info" effect="plain">
              {{ actionLabel(row.action as string) }}
            </el-tag>
          </template>

          <template #outcome="{ row }">
            <el-tag :type="outcomeTagType(row.outcome as string)" size="small" effect="plain">
              {{ outcomeLabel(row.outcome as string) }}
            </el-tag>
          </template>

          <template #ip="{ row }">
            <span class="is-code">{{ row.ip || '—' }}</span>
          </template>

          <template #detail="{ row }">
            <el-button text size="small" @click="openDetail(row as unknown as AuditLogItem)">
              查看
            </el-button>
          </template>
        </BasicTable>
      </template>
    </PageContainer>

    <el-dialog
      v-model="detailVisible"
      title="审计详情"
      width="min(92vw, 560px)"
      append-to-body
      destroy-on-close
      class="audit-detail-dialog dialog-body--scroll"
    >
      <template v-if="detailRow">
        <dl class="audit-facts">
          <div v-for="fact in detailFacts" :key="fact.label" class="audit-facts__cell">
            <dt class="audit-facts__key">{{ fact.label }}</dt>
            <dd class="audit-facts__val">{{ fact.value }}</dd>
          </div>
        </dl>

        <pre v-if="detailText" class="audit-json">{{ detailText }}</pre>
        <EmptyState
          v-else
          description="这条操作没有附加参数"
          reason="未记录附加参数"
        />
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.audit-actor {
  color: var(--ink);
}

/*
 * 全局只有 `td.is-code .cell` 一条等宽规则，插槽里的 span 命中不到；
 * 这里按同一口径补一条，不新造 class-name。
 */
.is-code {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
}

/* 事实格：label 压到 11px 让位给值，值走等宽以便对齐时间戳与 IP */
.audit-facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 8.5rem), 1fr));
  gap: var(--gap-2) var(--gap-3);
  margin: 0 0 var(--gap-3);
}

.audit-facts__cell {
  padding: var(--gap-2);
  border: 1px solid var(--rule-soft);
  border-radius: var(--radius);
  background: var(--surface-sunken);
  min-width: 0;
}

.audit-facts__key {
  font-size: var(--fs-kicker);
  line-height: 1.4;
  color: var(--mist);
}

.audit-facts__val {
  margin: var(--gap-1) 0 0;
  font-family: var(--mono);
  font-size: var(--fs-aux);
  line-height: 1.5;
  color: var(--ink);
  word-break: break-all;
}

/* 详情 JSON：整块围一圈细线即可，不加左竖条——它只是一段文本，不是引用 */
.audit-json {
  margin: 0;
  padding: var(--gap-2);
  background: var(--sheet-alt);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  line-height: 1.5;
  color: var(--ink);
  white-space: pre-wrap;
  word-break: break-all;
}
</style>


<style scoped src="./AdminList.css" />
