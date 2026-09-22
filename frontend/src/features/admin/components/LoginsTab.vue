<script setup lang="ts">
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
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import {
  LOGIN_ACTION_OPTIONS,
  OUTCOME_OPTIONS,
  actionLabel,
  outcomeLabel,
  outcomeTagType,
  tagVariant,
} from '../lib/adminDict'
import AdminLogFilters from './AdminLogFilters.vue'
import {
  EMPTY_LOG_FILTERS,
  createLogColumns,
  fetchLogPage,
  parseLogDetail,
  type LogFilters,
} from './logTableParts'

const tableRef = ref<InstanceType<typeof BasicTable>>()
const filters = ref<LogFilters>({ ...EMPTY_LOG_FILTERS })

const shared = createLogColumns({
  actorLabel: '登录账号',
  actorMinWidth: 150,
  actionLabel: '登录方式',
  actionWidth: 120,
  // 第三方登录常带 IPv6，比审计的 130 再留 10px
  ipWidth: 140,
})

const columns = ref<BasicTableColumn[]>([
  { ...shared.time, label: '登录时间' },
  shared.actor,
  shared.action,
  shared.outcome,
  shared.ip,
  {
    prop: 'detail_json',
    label: '客户端 / 认证信息',
    minWidth: 140,
    showOverflowTooltip: true,
    formatter: (row) => {
      const detail = parseLogDetail(row.detail_json)
      const agent = String(detail?.user_agent || '')
      const device = /Mobile|Android|iPhone/.test(agent) ? '移动设备' : agent ? '桌面设备' : ''
      const browser = /Edg\//.test(agent) ? 'Edge' : /Chrome\//.test(agent) ? 'Chrome' : /Firefox\//.test(agent) ? 'Firefox' : /Safari\//.test(agent) ? 'Safari' : ''
      const channel = detail?.provider === 'local' ? '账号密码' : String(detail?.provider || '')
      return [device, browser, channel, detail?.reason === 'invalid_credentials' ? '凭据校验失败' : ''].filter(Boolean).join(' · ') || '历史记录未采集客户端信息'
    },
  },
])

/** 登录方式、结果和关键词统一由服务端过滤，分页总数与筛选保持一致。 */
async function loadLogins(params: {
  currentPage: number
  pageSize: number
}): Promise<{ list: Record<string, unknown>[]; total: number }> {
  return fetchLogPage({
    fetcher: listAdminLogins,
    filters: filters.value,
    params,
    actionMode: 'server',
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
    

    <AdminLogFilters
      v-model="filters"
      keyword-placeholder="登录账号 / 用户名称"
      action-label="登录方式"
      :action-options="LOGIN_ACTION_OPTIONS"
      outcome-label="登录结果"
      :outcome-options="OUTCOME_OPTIONS"
      @search="reload"
      @reset="onReset"
    />

    <div class="admin-list__table">
      <BasicTable
        ref="tableRef"
        v-model:columns="columns"
        :request="loadLogins"
        :pagination="{ pageSize: 20, pageSizes: [20, 50, 100] }"
        :toolbar-config="{ refresh: true, custom: true }"
        :row-class-name="rowClassName"
        height="100%"
        row-key="id"
        empty-text="没有匹配的登录记录"
      >
        <template #actor="{ row }">
          <Tooltip v-if="row.actor_id" :delay-duration="200">
            <TooltipTrigger as-child>
              <span class="logins-actor">{{ row.actor_name || '系统' }}</span>
            </TooltipTrigger>
            <TooltipContent>账号 ID：{{ row.actor_id }}</TooltipContent>
          </Tooltip>
          <span v-else class="logins-actor">{{ row.actor_name || '系统' }}</span>
        </template>

        <template #action="{ row }">
          <UiBadge variant="info">
            {{ actionLabel(row.action as string) }}
          </UiBadge>
        </template>

        <template #outcome="{ row }">
          <UiBadge :variant="tagVariant(outcomeTagType(row.outcome as string))" dot>
            {{ outcomeLabel(row.outcome as string) }}
          </UiBadge>
        </template>

        <template #ip="{ row }">
          <span class="is-code">{{ row.ip || '—' }}</span>
        </template>
      </BasicTable>
    </div>
  </div>
</template>

<style scoped>
.logins-actor {
  color: var(--text-primary);
  font-weight: 500;
}

.is-code {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
}

.admin-pane :deep([data-slot='table-row'].logins-row--alert > td[data-slot='table-cell']) {
  background: color-mix(in oklab, var(--warn) 8%, transparent);
}
</style>

<style scoped src="./AdminList.css" />
