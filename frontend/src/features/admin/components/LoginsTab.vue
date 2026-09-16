<script setup lang="ts">
import { Search, RefreshRight } from '@element-plus/icons-vue'
/**
 * 登录日志。与审计日志同一条流、同一套「筛选栏 + BasicTable + 分页」骨架，
 * 但问的是另一个问题：谁、什么时候、用什么方式、从哪个 IP 进来的，成没成。
 *
 * 两条界面纪律：
 * 1. **失败行整行淡底**，不是只把「结果」那颗标记染色——爆破尝试的特征是
 *    同一账号连着几十行失败，一眼扫的是**行的密度**，不是单元格。
 * 2. **底色用告警琥珀，不用红绿**（D1：红绿只属于价格涨跌）。登录失败是
 *    运维告警，不是行情信号；红底会和盘面语义抢同一套色彩记忆。
 */
import { ref } from 'vue'

import { listAdminLogins } from '@/shared/api/admin'
import PageContainer from '@/shared/components/layout/PageContainer.vue'
import BasicForm from '@/shared/components/ui/BasicForm.vue'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import { LOGIN_ACTION_OPTIONS, actionLabel, outcomeLabel, outcomeTagType } from '../lib/adminDict'
import {
  EMPTY_LOG_FILTERS,
  createLogColumns,
  createLogFilterSchemas,
  fetchLogPage,
  parseLogDetail,
  type LogFilters,
} from './logTableParts'

const tableRef = ref<InstanceType<typeof BasicTable>>()
const filters = ref<LogFilters>({ ...EMPTY_LOG_FILTERS })

const filterSchemas = createLogFilterSchemas({
  keywordPlaceholder: '登录账号 / 用户名称',
  actionLabel: '登录方式',
  actionOptions: LOGIN_ACTION_OPTIONS,
  outcomeLabel: '登录结果',
})

const shared = createLogColumns({
  actorLabel: '登录账号',
  actorMinWidth: 150,
  actionLabel: '登录方式',
  actionWidth: 120,
  // 第三方登录常带 IPv6，比审计的 130 再留 10px
  ipWidth: 140,
})

const columns = ref<BasicTableColumn[]>([
  shared.time,
  shared.actor,
  shared.action,
  shared.outcome,
  shared.ip,
  {
    prop: 'detail_json',
    label: '备注',
    minWidth: 140,
    showOverflowTooltip: true,
    formatter: (row) => {
      const provider = parseLogDetail(row.detail_json)?.provider
      return provider ? `渠道：${String(provider)}` : '—'
    },
  },
])

/**
 * `listAdminLogins` 的后端**不收 `action` 参数**（它已按登录动作白名单收窄），
 * 所以「登录方式」只能在拿到当页之后本地过滤；分页总数仍报后端口径，
 * 不假装「登录方式也参与了分页」。与 `UsersTab` 处理角色筛选的口径一致。
 */
async function loadLogins(params: {
  currentPage: number
  pageSize: number
}): Promise<{ list: Record<string, unknown>[]; total: number }> {
  return fetchLogPage({
    fetcher: listAdminLogins,
    filters: filters.value,
    params,
    actionMode: 'client',
    errorMessage: '加载登录日志失败',
  })
}

function reload(): void {
  void tableRef.value?.restReload()
}

function onReset(): void {
  filters.value = { ...EMPTY_LOG_FILTERS }
  reload()
}

/** 失败登录整行打淡琥珀底；后端已按时间倒序返回，前端不再排序。 */
function rowClassName(data: { row: Record<string, unknown> }): string {
  return data.row.outcome === 'ok' ? '' : 'logins-row--alert'
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
          :request="loadLogins"
          :pagination="{ pageSize: 20, pageSizes: [20, 50, 100] }"
          :toolbar-config="{ refresh: true, custom: true }"
          :row-class-name="rowClassName"
          height="100%"
          row-key="id"
          stripe
          empty-text="没有匹配的登录记录"
        >
          <template #actor="{ row }">
            <el-tooltip
              v-if="row.actor_id"
              :content="`账号 ID：${row.actor_id}`"
              placement="top"
              :show-after="200"
            >
              <span class="logins-actor">{{ row.actor_name || '系统' }}</span>
            </el-tooltip>
            <span v-else class="logins-actor">{{ row.actor_name || '系统' }}</span>
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
        </BasicTable>
      </template>
    </PageContainer>
  </div>
</template>

<style scoped>
.logins-actor {
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

/*
 * 行底色落在 el-table 自己渲染的 td 上，scoped 属性够不着，只能 :deep。
 * 8% 是刻意压到「扫得出、读不烦」的下限：连着二十行也不会把表变成一片黄。
 */
.admin-pane :deep(.el-table__row.logins-row--alert > td.el-table__cell) {
  background: color-mix(in oklab, var(--warn) 8%, transparent);
}
</style>

<style scoped src="./AdminList.css" />
