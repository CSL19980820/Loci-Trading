<script setup lang="ts">
/**
 * 平台总览。
 *
 * 两处改造留档，避免下一轮又长回去：
 * 1. **四个数字卡走 `StatCard`**，不再自绘 `.metric-card`。原来那四块把标签字号、
 *    数值字号、卡内边距各写一遍魔法值，等于把 `StatCard` 的活重做了一次，还做歪了：
 *    数值字号比全站读数卡（--fs-tape / 26px）还大。口径说明从 tooltip 挪到卡上的
 *    `hint`——一行 12px 的副信息，比「悬停才看得见」更有用。
 * 2. **最近审计用 `BasicTable` 而不是时间线组件**。时间线自带左侧竖轴线与节点圆点，
 *    正是全站要清掉的那种左侧装饰线；而这块数据本来就是四列的表（时间 / 操作人 /
 *    类型 / 目标），表格能对齐列、能截断长目标串、能限高滚动，时间线三样都做不到。
 */
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { getAdminOverview } from '@/shared/api/admin'
import PageToolbar from '@/shared/components/layout/PageToolbar.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import BasicTable from '@/shared/components/ui/BasicTable.vue'
import type { BasicTableColumn } from '@/shared/components/ui/basicTableTypes'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import StatCard from '@/shared/components/ui/StatCard.vue'
import { toErrorMessage } from '@/shared/lib/errors'
import type { AdminOverviewResponse } from '@/shared/types/admin'
import { actionLabel, logTime } from '../lib/adminDict'
import TopLlmChart from './TopLlmChart.vue'

const loading = ref(false)
const overview = ref<AdminOverviewResponse>({
  users: 0,
  admins: 0,
  top_llm_usage: [],
  recent_audit: [],
  announcements: [],
  tenants: [],
})

/** 数字卡表驱动：口径进 `hint`，四张卡的版式由 StatCard 统一保证。 */
const metrics = computed<
  ReadonlyArray<{ key: string; label: string; value: number; hint: string }>
>(() => [
  { key: 'users', label: '注册用户数', value: overview.value.users, hint: '全平台注册账号' },
  { key: 'admins', label: '管理员数', value: overview.value.admins, hint: '拥有后台治理权限' },
  {
    key: 'tenants',
    label: '租户目录数',
    value: overview.value.tenants?.length ?? 0,
    hint: '独立隔离的数据目录',
  },
  {
    key: 'announcements',
    label: '全站公告数',
    value: overview.value.announcements.length,
    hint: '已发布的系统通知',
  },
])

const auditRows = computed(
  () => overview.value.recent_audit as unknown as Record<string, unknown>[],
)

const auditColumns = ref<BasicTableColumn[]>([
  {
    prop: 'occurred_at',
    label: '时间',
    width: 170,
    align: 'center',
    headerAlign: 'center',
    formatter: (row) => logTime(row.occurred_at as string),
  },
  {
    prop: 'actor_name',
    label: '操作人',
    minWidth: 120,
    showOverflowTooltip: true,
    formatter: (row) => (row.actor_name as string) || '系统',
  },
  {
    prop: 'action',
    label: '操作类型',
    width: 130,
    align: 'center',
    headerAlign: 'center',
    slotName: 'action',
  },
  {
    prop: 'target',
    label: '目标对象',
    minWidth: 130,
    showOverflowTooltip: true,
    formatter: (row) => (row.target as string) || '—',
  },
])

async function loadData(): Promise<void> {
  loading.value = true
  try {
    overview.value = await getAdminOverview()
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '加载总览数据失败'))
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadData()
})
</script>

<template>
  <div class="admin-pane" v-loading="loading">
    <PageToolbar dense seamless>
      <template #actions>
        <el-button
          :icon="Refresh"
          circle
          :loading="loading"
          title="刷新总览"
          aria-label="刷新总览"
          @click="loadData"
        />
      </template>
    </PageToolbar>

    <div class="admin-pane__scroll">
      <div class="overview-metrics">
        <StatCard
          v-for="metric in metrics"
          :key="metric.key"
          :label="metric.label"
          :value="metric.value"
          :hint="metric.hint"
        />
      </div>

      <div class="overview-panels">
        <Sheet title="当月大模型用量" chip="前 10 名" padded>
          <TopLlmChart :items="overview.top_llm_usage" />
        </Sheet>

        <Sheet title="最近审计事件" chip="最新 20 条" padded>
          <BasicTable
            v-if="auditRows.length > 0"
            v-model:columns="auditColumns"
            :data-source="auditRows"
            :pagination="false"
            row-key="id"
            stripe
          >
            <template #action="{ row }">
              <el-tag size="small" type="info" effect="plain">
                {{ actionLabel(row.action as string) }}
              </el-tag>
            </template>
          </BasicTable>
          <EmptyState v-else description="还没有审计事件" reason="管理动作会实时落在这里" />
        </Sheet>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 卡高由内容决定：align-items:start 让只有一张卡有副信息时不被拉齐成死白 */
.overview-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--gap-2);
  align-items: start;
  flex: 0 0 auto;
}

/*
 * 总览是「一屏读完」的看板：两块面板吃满数字卡以下的**全部**剩余高度。
 * 原来两块都由内容定高（图表 280px、审计表 max-height 320px），
 * 于是 1080p 下半屏是一整片死白，而右边的审计表还在 320px 的窗口里滚 20 条。
 * min-height 是矮视口的下限：比这更矮就让 .admin-pane__scroll 去滚，不把图表压扁。
 */
.overview-panels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--gap-2);
  flex: 1 1 auto;
  min-height: 24rem;
}

/*
 * 980px = 全站断点（侧栏消失、底栏出现的那条线），不另立门户。
 * 单列后两块各自读内容高：撑满只会让人滚两屏才看到审计表。
 */
@media (max-width: 980px) {
  .overview-panels {
    grid-template-columns: 1fr;
    flex: 0 0 auto;
    min-height: 0;
  }
}

/*
 * grid 子项要显式收缩位（宽度不撑破列），并且自己是纵向 flex：
 * 高度这才能一路传到图表画布与表体，由它们在内层滚。
 */
.overview-panels > .sheet {
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.overview-panels > .sheet :deep(.sheet-slot) {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* 空态没有内容高度，居中比顶在标题下更像「这里本来该有东西」 */
.overview-panels > .sheet :deep(.empty-state) {
  margin: auto 0;
}
</style>
