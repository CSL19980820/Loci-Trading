<script setup lang="ts">
/**
 * 用户管理。全站统一的「筛选栏 + BasicTable + RowActions」列表骨架，
 * 不再自绘 filter-bar / el-table / pagination-bar。
 *
 * 两条界面纪律：
 * 1. **用户名称与登录账号分列、注册与最后登录分列**——搜索到人要能一眼确认
 *    「点的是不是他」，挤成一格靠 @handle 副行区分，行高一压就糊成一团。
 * 2. **操作列只留启用 / 停用**，其余（角色、配额、口令、通知）沉进「更多」。
 *    五颗常驻文字按钮既把操作列撑到 230px，也把危险动作摆到了顺手位置。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { listAdminUsers, setUserRole, setUserStatus } from '@/shared/api/admin'
import PageContainer from '@/shared/components/layout/PageContainer.vue'
import BasicForm from '@/shared/components/ui/BasicForm.vue'
import type { BasicFormSchema } from '@/shared/components/ui/basicFormTypes'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import ListToolbar, { type ListToolbarConfig } from '@/shared/components/ui/ListToolbar.vue'
import RowActions, { type RowAction } from '@/shared/components/ui/RowActions.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import { toErrorMessage } from '@/shared/lib/errors'
import { useUserStore } from '@/shared/stores/user'
import type { AdminUserItem } from '@/shared/types/admin'
import type { Role, UserStatus } from '@/shared/types/auth'
import {
  ROLE_OPTIONS,
  STATUS_OPTIONS,
  accountTime,
  roleLabel,
  roleTagType,
  statusLabel,
  statusTagType,
  tenantHint,
  tenantLabel,
} from '../lib/adminDict'
import { formatTokens } from '../lib/adminFormat'
import CreateUserDialog from './CreateUserDialog.vue'
import NotifyUserDialog from './NotifyUserDialog.vue'
import ResetPasswordDialog from './ResetPasswordDialog.vue'
import UserQuotaDialog from './UserQuotaDialog.vue'

const userStore = useUserStore()
const currentUserId = computed(() => userStore.user?.id)

const tableRef = ref<InstanceType<typeof BasicTable>>()
const filters = ref<Record<string, unknown>>({ keyword: '', status: '', role: '' })

const selectedUser = ref<AdminUserItem | null>(null)
const createDialogVisible = ref(false)
const quotaDialogVisible = ref(false)
const resetPwdDialogVisible = ref(false)
const notifyDialogVisible = ref(false)

const filterSchemas: BasicFormSchema[] = [
  {
    field: 'keyword',
    label: '关键词',
    componentProps: { placeholder: '登录账号 / 用户名称 / 邮箱', clearable: true },
  },
  {
    field: 'status',
    label: '账号状态',
    component: 'select',
    componentProps: { placeholder: '全部', clearable: true, options: [...STATUS_OPTIONS] },
  },
  {
    field: 'role',
    label: '角色',
    component: 'select',
    componentProps: { placeholder: '全部', clearable: true, options: [...ROLE_OPTIONS] },
  },
]

const columns = ref<BasicTableColumn[]>([
  { prop: 'display_name', label: '用户名称', minWidth: 140, showOverflowTooltip: true },
  {
    prop: 'username',
    label: '登录账号',
    minWidth: 130,
    showOverflowTooltip: true,
    slotName: 'account',
  },
  // 长邮箱不截断会把 28px 的行折成两行；截断 + tooltip 才守得住密度（D3）
  { prop: 'email', label: '邮箱', minWidth: 170, showOverflowTooltip: true, slotName: 'email' },
  {
    prop: 'role',
    label: '角色',
    width: 96,
    align: 'center',
    headerAlign: 'center',
    slotName: 'role',
  },
  {
    prop: 'status',
    label: '状态',
    width: 88,
    align: 'center',
    headerAlign: 'center',
    slotName: 'status',
  },
  {
    prop: 'tenant_id',
    label: '租户',
    width: 96,
    align: 'center',
    headerAlign: 'center',
    slotName: 'tenant',
  },
  {
    prop: 'usage',
    label: '当月用量 / 额度',
    width: 140,
    align: 'right',
    headerAlign: 'right',
    slotName: 'tokens',
  },
  {
    prop: 'created_at',
    label: '注册时间',
    width: 140,
    align: 'center',
    headerAlign: 'center',
    formatter: (row) => accountTime(row.created_at as string),
  },
  {
    prop: 'last_login_at',
    label: '最后登录时间',
    width: 140,
    align: 'center',
    headerAlign: 'center',
    formatter: (row) => accountTime(row.last_login_at as string, '从未登录'),
  },
  {
    prop: 'actions',
    label: '操作',
    width: 128,
    fixed: 'right',
    align: 'center',
    headerAlign: 'center',
    slotName: 'actions',
  },
])

const toolbarConfig = computed<ListToolbarConfig>(() => ({
  create: {
    onClick: () => {
      createDialogVisible.value = true
    },
  },
}))

/**
 * 角色维度后端没有查询参数，只能在**当前页内**过滤；分页总数仍报后端口径，
 * 不假装「角色也参与了分页」。真要按角色分页需要后端加参数，不在本轮范围。
 */
async function loadUsers(params: {
  currentPage: number
  pageSize: number
}): Promise<{ list: Record<string, unknown>[]; total: number }> {
  try {
    const role = String(filters.value.role || '')
    const res = await listAdminUsers({
      keyword: String(filters.value.keyword || '').trim() || undefined,
      status: String(filters.value.status || '') || undefined,
      limit: params.pageSize,
      offset: (params.currentPage - 1) * params.pageSize,
    })
    const items = role ? res.items.filter((item) => item.role === role) : res.items
    return { list: items as unknown as Record<string, unknown>[], total: res.total }
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '加载用户列表失败'))
    return { list: [], total: 0 }
  }
}

function reload(): void {
  void tableRef.value?.restReload()
}

function onReset(): void {
  filters.value = { keyword: '', status: '', role: '' }
  reload()
}

function openQuotaDialog(row: AdminUserItem): void {
  selectedUser.value = row
  quotaDialogVisible.value = true
}

function openResetPwdDialog(row: AdminUserItem): void {
  selectedUser.value = row
  resetPwdDialogVisible.value = true
}

function openNotifyDialog(row: AdminUserItem): void {
  selectedUser.value = row
  notifyDialogVisible.value = true
}

async function handleToggleRole(row: AdminUserItem): Promise<void> {
  const isTargetAdmin = row.role === 'admin'
  const newRole: Role = isTargetAdmin ? 'member' : 'admin'

  if (isTargetAdmin && row.id === currentUserId.value) {
    ElMessage.warning('不能取消自己的管理员身份')
    return
  }

  if (isTargetAdmin) {
    const confirmed = await confirmDangerous(
      `确定要将管理员「${row.display_name || row.username}」降级为普通成员吗？`,
      '角色变更确认',
      '确认降级',
    )
    if (!confirmed) return
  }

  try {
    await setUserRole(row.id, newRole)
    ElMessage.success(`已将该用户角色更新为${roleLabel(newRole)}`)
    reload()
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '修改角色失败'))
  }
}

async function handleToggleStatus(row: AdminUserItem): Promise<void> {
  const isTargetActive = row.status === 'active'
  const newStatus: UserStatus = isTargetActive ? 'disabled' : 'active'

  if (isTargetActive && row.id === currentUserId.value) {
    ElMessage.warning('不能停用自己')
    return
  }

  if (isTargetActive) {
    const confirmed = await confirmDangerous(
      `确定要停用用户「${row.display_name || row.username}」吗？停用后该用户所有会话将被立即强制注销。`,
      '账号停用确认',
      '确认停用',
    )
    if (!confirmed) return
  }

  try {
    await setUserStatus(row.id, newStatus)
    ElMessage.success(`已${isTargetActive ? '停用' : '启用'}该账号`)
    reload()
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '修改状态失败'))
  }
}

function rowActions(row: AdminUserItem): RowAction[] {
  const isSelf = row.id === currentUserId.value
  const isActive = row.status === 'active'
  return [
    {
      key: 'status',
      label: isActive ? '停用' : '启用',
      type: isActive ? 'danger' : 'success',
      disabled: isSelf && isActive,
      tip: '不能停用自己',
      onClick: () => void handleToggleStatus(row),
    },
    {
      key: 'role',
      label: row.role === 'admin' ? '降为普通成员' : '设为管理员',
      disabled: isSelf && row.role === 'admin',
      onClick: () => void handleToggleRole(row),
    },
    { key: 'quota', label: '调整配额', onClick: () => openQuotaDialog(row) },
    { key: 'notify', label: '发送站内通知', onClick: () => openNotifyDialog(row) },
    {
      key: 'password',
      label: '重置口令',
      type: 'danger',
      divided: true,
      onClick: () => openResetPwdDialog(row),
    },
  ]
}

defineExpose({ handleToggleRole, handleToggleStatus })
</script>

<template>
  <div class="admin-pane">
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
          <el-button type="primary" @click="reload">查询</el-button>
          <el-button @click="onReset">重置</el-button>
        </div>
      </template>

      <template #main>
        <BasicTable
          ref="tableRef"
          v-model:columns="columns"
          :request="loadUsers"
          :pagination="{ pageSize: 20, pageSizes: [20, 50, 100] }"
          :toolbar-config="{ refresh: true, custom: true }"
          row-key="id"
          stripe
          empty-text="没有匹配的账号"
        >
          <template #toolbarButtons>
            <ListToolbar :config="toolbarConfig" />
          </template>

          <template #account="{ row }">
            <span class="is-code">{{ row.username }}</span>
          </template>

          <template #email="{ row }">
            <span v-if="!row.email" class="admin-pane__dim">未绑定</span>
            <template v-else>
              <span>{{ row.email }}</span>
              <el-tag
                v-if="row.email_verified_at"
                size="small"
                type="success"
                effect="plain"
                class="admin-pane__verified"
              >
                已验证
              </el-tag>
            </template>
          </template>

          <template #role="{ row }">
            <el-tag :type="roleTagType(row.role as string)" size="small" effect="plain">
              {{ roleLabel(row.role as string) }}
            </el-tag>
          </template>

          <template #status="{ row }">
            <el-tag :type="statusTagType(row.status as string)" size="small" effect="plain">
              {{ statusLabel(row.status as string) }}
            </el-tag>
          </template>

          <template #tenant="{ row }">
            <el-tooltip
              :content="tenantHint(row.tenant_id as string)"
              :disabled="!row.tenant_id"
              placement="top"
              :show-after="200"
            >
              <span>{{ tenantLabel(row.tenant_id as string) }}</span>
            </el-tooltip>
          </template>

          <template #tokens="{ row }">
            <span class="admin-pane__usage">
              {{ formatTokens((row.usage as { llm_tokens?: number })?.llm_tokens) }}
            </span>
            <span class="admin-pane__dim">
              /
              {{ formatTokens((row.quota as { llm_monthly_tokens?: number })?.llm_monthly_tokens) }}
            </span>
          </template>

          <template #actions="{ row }">
            <RowActions :actions="rowActions(row as unknown as AdminUserItem)" :max-visible="1" />
          </template>
        </BasicTable>
      </template>
    </PageContainer>

    <CreateUserDialog v-model="createDialogVisible" @created="reload" />
    <UserQuotaDialog v-model:visible="quotaDialogVisible" :user="selectedUser" @saved="reload" />
    <ResetPasswordDialog
      v-model:visible="resetPwdDialogVisible"
      :user="selectedUser"
      @saved="reload"
    />
    <NotifyUserDialog v-model:visible="notifyDialogVisible" :user="selectedUser" />
  </div>
</template>

<style scoped>
.admin-pane__usage {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
  color: var(--seal-ink);
  font-weight: 600;
}

.admin-pane__dim {
  color: var(--mist);
}

.admin-pane__verified {
  margin-left: var(--gap-1);
}
</style>
