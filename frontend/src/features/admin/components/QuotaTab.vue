<script setup lang="ts">
/**
 * 配额管理：批量调整 + 用户配额一览。
 *
 * ## 取舍：一格一个数字，取代「勾了才提交 + 不限勾选框」
 *
 * 旧版每项配额挂三个控件（`调整` 复选框 + 数值框 + `不限` 复选框），六项就是
 * 十八个控件、两层互斥开关（没勾「调整」时数值框与「不限」都要置灰、不参与校验、
 * 不进 payload）。三条规则各自都得有实现，界面上一行也塞不下三个控件。
 *
 * 现在**每项只有一个数值框**，口径靠值本身表达：
 * - **留空（`undefined`）= 这项不改**，不进 payload；
 * - **`-1` = 不限**（与后端一致：配额字段 -1 表示无上限）；
 * - `≥ 0` = 具体上限。
 *
 * 于是「不改」与「不限」从两个开关变成两个值，六项配额一行三列就排得下，
 * 校验也只剩 `min: -1` 一条。写入语义仍走 `adminFormat.ts` 的 `uiValueToQuota`
 * （负值 → -1，正值 → 向下取整且不小于 0），不在本文件另造一套取整规则。
 *
 * 另一处口径：用户表用 `request` 分页，**换页会清空勾选**（BasicTable 的选择列
 * 不带 reserve-selection），所以「已选 N 人」永远只表示当前页的勾选，不会出现
 * 「跨页勾了 80 人却只有 20 人被改」的静默偏差。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { listAdminUsers, setUserQuota } from '@/shared/api/admin'
import BasicForm from '@/shared/components/ui/BasicForm.vue'
import type { BasicFormSchema } from '@/shared/components/ui/basicFormTypes'
import BasicTable from '@/shared/components/ui/BasicTable.vue'
import type { BasicTableColumn } from '@/shared/components/ui/basicTableTypes'
import Sheet from '@/shared/components/layout/Sheet.vue'
import { toErrorMessage } from '@/shared/lib/errors'
import type { AdminUserItem, SetQuotaPayload } from '@/shared/types/admin'
import type { UserQuota } from '@/shared/types/auth'
import { formatTokens, uiValueToQuota } from '../lib/adminFormat'

/** 六项配额的字段表：表单 schema 与 payload 键从同一处派生，不在模板里抄六遍。 */
const QUOTA_FIELDS: ReadonlyArray<{
  field: keyof SetQuotaPayload
  label: string
  hint: string
  step: number
}> = [
  {
    field: 'llm_monthly_tokens',
    label: '月度额度',
    hint: '每月大模型 Token 上限',
    step: 50000,
  },
  {
    field: 'llm_daily_calls',
    label: '每日调用',
    hint: '每天可向 AI 发起的请求次数',
    step: 50,
  },
  {
    field: 'strategy_slots',
    label: '策略槽位',
    hint: '可创建或保存的私有策略数',
    step: 5,
  },
  {
    field: 'publish_slots',
    label: '发布槽位',
    hint: '可向广场公开发布的策略数',
    step: 1,
  },
  {
    field: 'job_slots',
    label: '定时任务',
    hint: '自建定时任务上限；系统托管的选股 / 情报任务不占额度',
    step: 1,
  },
  {
    field: 'storage_mb',
    label: '目录容量',
    hint: '私有目录软上限，单位 MB；超限只加速清理临时数据，不拒写入',
    step: 512,
  },
]

/** 表格里的只读配额列。与上面的字段表分开：这四列不参与批量编辑。 */
const QUOTA_COLUMNS: ReadonlyArray<{ key: keyof UserQuota; label: string; width: number }> = [
  { key: 'llm_monthly_tokens', label: '月度额度', width: 110 },
  { key: 'llm_daily_calls', label: '每日调用', width: 100 },
  { key: 'strategy_slots', label: '策略槽位', width: 100 },
  { key: 'publish_slots', label: '发布槽位', width: 100 },
]

const tableRef = ref<InstanceType<typeof BasicTable>>()
const keyword = ref('')
const applying = ref(false)
const selectedUsers = ref<AdminUserItem[]>([])
const batchForm = ref<Record<string, unknown>>({})

const batchSchemas: BasicFormSchema[] = QUOTA_FIELDS.map((item) => ({
  field: item.field,
  label: item.label,
  component: 'input-number',
  hint: item.hint,
  componentProps: {
    // 下界必须是 -1（不限），所以不能开 stepStrictly：步长 50000 会把 -1 吸成 0
    min: -1,
    step: item.step,
    precision: 0,
    controlsPosition: 'right',
    placeholder: '留空不改',
  },
}))

const columns = ref<BasicTableColumn[]>([
  { type: 'selection', width: 44 },
  { prop: 'display_name', label: '用户名称', minWidth: 140, showOverflowTooltip: true },
  { prop: 'username', label: '登录账号', minWidth: 130, slotName: 'account' },
  ...QUOTA_COLUMNS.map<BasicTableColumn>((col) => ({
    prop: col.key,
    label: col.label,
    width: col.width,
    align: 'right',
    headerAlign: 'right',
    formatter: (row) => formatTokens((row.quota as UserQuota | undefined)?.[col.key]),
  })),
])

const selectedCount = computed(() => selectedUsers.value.length)

async function loadUsers(params: {
  currentPage: number
  pageSize: number
}): Promise<{ list: Record<string, unknown>[]; total: number }> {
  try {
    const res = await listAdminUsers({
      keyword: keyword.value.trim() || undefined,
      limit: params.pageSize,
      offset: (params.currentPage - 1) * params.pageSize,
    })
    return { list: res.items as unknown as Record<string, unknown>[], total: res.total }
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '加载用户列表失败'))
    return { list: [], total: 0 }
  }
}

function reload(): void {
  selectedUsers.value = []
  void tableRef.value?.restReload()
}

function onSelectionChange(rows: Record<string, unknown>[]): void {
  selectedUsers.value = rows as unknown as AdminUserItem[]
}

/** 留空的项不进 payload；负值统一收敛成 -1（不限），正值走 uiValueToQuota 取整。 */
function buildPayload(): SetQuotaPayload {
  const payload: SetQuotaPayload = {}
  for (const item of QUOTA_FIELDS) {
    const raw = batchForm.value[item.field]
    if (raw === undefined || raw === null || raw === '') continue
    const num = Number(raw)
    if (!Number.isFinite(num)) continue
    payload[item.field] = num < 0 ? uiValueToQuota(true, 0) : uiValueToQuota(false, num)
  }
  return payload
}

async function handleApplyBatch(): Promise<void> {
  if (selectedUsers.value.length === 0) {
    ElMessage.warning('先在下方勾选用户')
    return
  }

  const payload = buildPayload()
  if (Object.keys(payload).length === 0) {
    ElMessage.warning('至少填一项配额；留空的项不会改动')
    return
  }

  applying.value = true
  let successCount = 0
  const failures: string[] = []

  for (const user of selectedUsers.value) {
    try {
      await setUserQuota(user.id, payload)
      successCount++
    } catch (caught: unknown) {
      // 只数个数不留原因，管理员看到「3 失败」后无从下手：是权限不够、
      // 某个用户已删除，还是服务端 500？把前两条原因原样带出来。
      failures.push(`${user.username}：${toErrorMessage(caught, '未知错误')}`)
    }
  }

  applying.value = false
  if (failures.length === 0) {
    ElMessage.success(`已为 ${successCount} 名用户更新配额`)
  } else {
    ElMessage.warning(
      `${successCount} 成功，${failures.length} 失败。${failures.slice(0, 2).join('；')}`,
    )
  }
  reload()
}
</script>

<template>
  <div class="admin-pane">
    <Sheet class="quota-batch" title="批量调整配额" :chip="`已选 ${selectedCount} 人`" padded>
      <template #actions>
        <el-button
          type="primary"
          :disabled="selectedCount === 0"
          :loading="applying"
          @click="handleApplyBatch"
        >
          应用到所选
        </el-button>
      </template>

      <BasicForm
        v-model="batchForm"
        :schemas="batchSchemas"
        :columns="3"
        :input-debounce-ms="0"
        hint="留空的项不改动；填 -1 表示不限"
      />
    </Sheet>

    <BasicTable
      ref="tableRef"
      v-model:columns="columns"
      :request="loadUsers"
      :pagination="{ pageSize: 20, pageSizes: [20, 50, 100] }"
      :toolbar-config="{ refresh: true }"
      row-key="id"
      stripe
      empty-text="没有匹配的账号"
      @selection-change="onSelectionChange"
      @refresh="selectedUsers = []"
    >
      <template #toolbarButtons>
        <el-input
          v-model="keyword"
          class="quota-search"
          placeholder="登录账号 / 用户名称"
          size="small"
          clearable
          @keyup.enter="reload"
          @clear="reload"
        />
        <el-button size="small" type="primary" @click="reload">查询</el-button>
      </template>

      <template #account="{ row }">
        <span class="is-code">{{ row.username }}</span>
      </template>
    </BasicTable>
  </div>
</template>

<style scoped>
/*
 * 批量表单固定在上，表格吃满剩余高度并在内部滚。
 * 外边距给 --gap-2：Sheet 与表格工具栏各带一条 hairline，贴在一起会叠成一道脏边。
 */
.quota-batch {
  flex-shrink: 0;
  margin: var(--gap-2);
}

.quota-search {
  width: 12rem;
}
</style>
