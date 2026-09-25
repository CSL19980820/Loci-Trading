<script setup lang="ts">
/**
 * 用户管理：桌面 = 筛选行 + BasicTable；≤640 = 用户卡列表（头像字母 + 名称 / 账号两行 +
 * 角色 / 状态徽标 + 当月用量 + `⋯` 菜单），整卡不再横滑八列。
 * 危险动作（停用 / 降级 / 重置口令）一律经 confirmDangerous 二次确认。
 */
import { Ellipsis, Plus, RefreshCw, Search } from '@lucide/vue'
import { useMediaQuery } from '@vueuse/core'

import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { toast } from 'vue-sonner'

import { listAdminUsers, setUserRole, setUserStatus } from '@/shared/api/admin'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import { Button } from '@/shared/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Input } from '@/shared/components/ui/input'
import RowActions, { type RowAction } from '@/shared/components/ui/RowActions.vue'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
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
  tagVariant,
} from '../lib/adminDict'
import { formatTokens } from '../lib/adminFormat'
import CreateUserDialog from './CreateUserDialog.vue'
import NotifyUserDialog from './NotifyUserDialog.vue'
import ResetPasswordDialog from './ResetPasswordDialog.vue'

const ALL = '__all__'
const MOBILE_PAGE = 30

const userStore = useUserStore()
const currentUserId = computed(() => userStore.user?.id)
const isMobile = useMediaQuery('(max-width: 640px)')

const tableRef = ref<InstanceType<typeof BasicTable>>()
const filters = ref<{ keyword: string; status: string; role: string }>({ keyword: '', status: '', role: '' })

const selectedUser = ref<AdminUserItem | null>(null)
const createDialogVisible = ref(false)
const resetPwdDialogVisible = ref(false)
const notifyDialogVisible = ref(false)

/** Select 不接受空字符串当「全部」，用哨兵值来回映射 */
const statusPick = computed({
  get: () => String(filters.value.status || '') || ALL,
  set: (next: string) => {
    filters.value = { ...filters.value, status: next === ALL ? '' : next }
  },
})
const rolePick = computed({
  get: () => String(filters.value.role || '') || ALL,
  set: (next: string) => {
    filters.value = { ...filters.value, role: next === ALL ? '' : next }
  },
})

const columns = ref<BasicTableColumn[]>([
  { prop: 'display_name', label: '用户', minWidth: 200, slotName: 'identity' },
  // 长邮箱不截断会把 28px 的行折成两行；截断 + tooltip 才守得住密度（D3）
  { prop: 'email', label: '邮箱', minWidth: 220, showOverflowTooltip: true, slotName: 'email' },
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
    prop: 'usage',
    label: '当月 Tokens',
    width: 150,
    align: 'right',
    headerAlign: 'right',
    slotName: 'tokens',
  },
  {
    prop: 'last_login_at',
    label: '最后登录',
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

function requestUsers(offset: number, limit: number, signal: AbortSignal) {
  return listAdminUsers({
    keyword: filters.value.keyword.trim() || undefined,
    status: filters.value.status || undefined,
    role: (filters.value.role || undefined) as Role | undefined,
    limit,
    offset,
  }, signal)
}

let desktopController: AbortController | undefined
async function loadUsers(params: {
  currentPage: number
  pageSize: number
}): Promise<{ list: Record<string, unknown>[]; total: number }> {
  desktopController?.abort()
  const controller = new AbortController()
  desktopController = controller
  try {
    const res = await requestUsers((params.currentPage - 1) * params.pageSize, params.pageSize, controller.signal)
    return { list: res.items as unknown as Record<string, unknown>[], total: res.total }
  } catch (caught: unknown) {
    if (!controller.signal.aborted) toast.error(toErrorMessage(caught, '加载用户列表失败'))
    return { list: [], total: 0 }
  }
}

/* ─── 手机端卡列表：自己取第一页，「加载更多」追加 ─── */
const mobileRows = ref<AdminUserItem[]>([])
const mobileTotal = ref(0)
const mobileLoading = ref(false)
let mobileOffset = 0
let mobileGeneration = 0
let mobileController: AbortController | undefined

function invalidateMobile(): void {
  mobileGeneration += 1
  mobileController?.abort()
  mobileLoading.value = false
}

async function loadMobile(append = false): Promise<void> {
  if (append && (mobileLoading.value || mobileOffset >= mobileTotal.value)) return
  invalidateMobile()
  const generation = mobileGeneration
  const controller = new AbortController()
  mobileController = controller
  if (!append) {
    mobileRows.value = []
    mobileTotal.value = 0
    mobileOffset = 0
  }
  mobileLoading.value = true
  const offset = mobileOffset
  try {
    const page = await requestUsers(offset, MOBILE_PAGE, controller.signal)
    if (generation !== mobileGeneration) return
    // 游标跟随服务端返回的行数，不能从本地展示行数或角色过滤结果反推页码。
    mobileOffset = offset + page.items.length
    mobileRows.value = append ? [...mobileRows.value, ...page.items] : page.items
    mobileTotal.value = page.total
  } catch (caught: unknown) {
    if (generation === mobileGeneration && !controller.signal.aborted) {
      toast.error(toErrorMessage(caught, '加载用户列表失败'))
    }
  } finally {
    if (generation === mobileGeneration) mobileLoading.value = false
  }
}

watch(
  isMobile,
  (mobile) => {
    desktopController?.abort()
    invalidateMobile()
    if (mobile) void loadMobile()
  },
  { immediate: true },
)

watch(filters, reload, { deep: true })
onBeforeUnmount(() => {
  desktopController?.abort()
  invalidateMobile()
})

function reload(): void {
  if (isMobile.value) {
    void loadMobile()
    return
  }
  void tableRef.value?.restReload()
}

function onReset(): void {
  if (!filters.value.keyword && !filters.value.status && !filters.value.role) {
    reload()
    return
  }
  filters.value = { keyword: '', status: '', role: '' }
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
  const newRole: Role = isTargetAdmin ? 'visitor' : 'admin'

  if (isTargetAdmin && row.id === currentUserId.value) {
    toast.warning('不能取消自己的管理员身份')
    return
  }

  if (isTargetAdmin) {
    const confirmed = await confirmDangerous(
      `确定要将管理员「${row.display_name || row.username}」降级为只读访客吗？`,
      '角色变更确认',
      '确认降级',
    )
    if (!confirmed) return
  }

  try {
    await setUserRole(row.id, newRole)
    toast.success(`已将该用户角色更新为${roleLabel(newRole)}`)
    reload()
  } catch (caught: unknown) {
    toast.error(toErrorMessage(caught, '修改角色失败'))
  }
}

async function handleToggleStatus(row: AdminUserItem): Promise<void> {
  const isTargetActive = row.status === 'active'
  const newStatus: UserStatus = isTargetActive ? 'disabled' : 'active'

  if (isTargetActive && row.id === currentUserId.value) {
    toast.warning('不能停用自己')
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
    toast.success(`已${isTargetActive ? '停用' : '启用'}该账号`)
    reload()
  } catch (caught: unknown) {
    toast.error(toErrorMessage(caught, '修改状态失败'))
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
      label: row.role === 'admin' ? '降为只读访客' : '设为管理员',
      disabled: isSelf && row.role === 'admin',
      onClick: () => void handleToggleRole(row),
    },
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

function initial(row: AdminUserItem): string {
  return (row.display_name || row.username || '?').trim().slice(0, 1).toUpperCase()
}


defineExpose({ handleToggleRole, handleToggleStatus })
</script>

<template>
  <div class="admin-pane users">
    <div class="users__toolbar" role="search">
      <div class="users__search">
        <Search class="users__search-icon" aria-hidden="true" />
        <Input
          v-model="filters.keyword"
          size="sm"
          class="users__search-input"
          placeholder="登录账号 / 用户名称 / 邮箱"
          aria-label="搜索用户"
          @keyup.enter="reload"
        />
      </div>
      <Select v-model="statusPick">
        <SelectTrigger size="sm" class="users__select" aria-label="账号状态">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem :value="ALL">全部状态</SelectItem>
          <SelectItem v-for="opt in STATUS_OPTIONS" :key="String(opt.value)" :value="String(opt.value)">{{ opt.label }}</SelectItem>
        </SelectContent>
      </Select>
      <Select v-model="rolePick">
        <SelectTrigger size="sm" class="users__select" aria-label="角色">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem :value="ALL">全部角色</SelectItem>
          <SelectItem v-for="opt in ROLE_OPTIONS" :key="String(opt.value)" :value="String(opt.value)">{{ opt.label }}</SelectItem>
        </SelectContent>
      </Select>
      <div class="users__toolbar-actions">
        <Button v-if="isMobile" size="sm" @click="createDialogVisible = true"><Plus />新建账号</Button>
        <Button access="read" size="sm" variant="outline" @click="reload"><Search />查询</Button>
        <Button size="sm" variant="ghost" @click="onReset"><RefreshCw />重置</Button>
      </div>
    </div>

    <!-- ≤640：卡列表 -->
    <div v-if="isMobile" class="users__cards">
      <template v-if="mobileLoading && !mobileRows.length">
        <Skeleton v-for="n in 4" :key="n" class="h-[72px] w-full rounded-lg" />
      </template>
      <article v-for="row in mobileRows" :key="row.id" class="user-card" :class="{ 'is-disabled': row.status !== 'active' }">
        <span class="user-card__avatar" aria-hidden="true">{{ initial(row) }}</span>
        <div class="user-card__body">
          <div class="user-card__top">
            <strong class="user-card__name">{{ row.display_name || row.username }}</strong>
            <UiBadge :variant="tagVariant(roleTagType(row.role))">{{ roleLabel(row.role) }}</UiBadge>
            <UiBadge v-if="row.status !== 'active'" :variant="tagVariant(statusTagType(row.status))" dot>{{ statusLabel(row.status) }}</UiBadge>
          </div>
          <p class="user-card__sub">
            <span class="user-card__account">@{{ row.username }}</span>
            <span v-if="row.email" class="user-card__email">{{ row.email }}</span>
          </p>
          <div class="user-card__usage"><span class="user-card__usage-text">当月 {{ formatTokens(row.usage?.llm_tokens) }} Tokens</span></div>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger as-child>
            <Button variant="ghost" size="icon" class="user-card__more" :aria-label="`${row.display_name || row.username} 的操作`">
              <Ellipsis />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <template v-for="(action, i) in rowActions(row)" :key="action.key">
              <DropdownMenuSeparator v-if="action.divided && i > 0" />
              <DropdownMenuItem
                :disabled="action.disabled"
                :variant="action.type === 'danger' ? 'destructive' : 'default'"
                @select="action.onClick?.()"
              >
                {{ action.label }}
              </DropdownMenuItem>
            </template>
          </DropdownMenuContent>
        </DropdownMenu>
      </article>
      <EmptyState v-if="!mobileLoading && !mobileRows.length" description="没有匹配的账号" reason="换个关键词或清掉筛选" />
      <Button
        v-if="mobileRows.length < mobileTotal"
        variant="outline"
        class="users__more"
        :disabled="mobileLoading"
        @click="loadMobile(true)"
      >
        加载更多（{{ mobileRows.length }} / {{ mobileTotal }}）
      </Button>
    </div>

    <!-- 桌面：表格 -->
    <div v-else class="users__table">
      <BasicTable
        ref="tableRef"
        v-model:columns="columns"
        :request="loadUsers"
        :pagination="{ pageSize: 20, pageSizes: [20, 50, 100] }"
        :toolbar-config="{ refresh: true, custom: true }"
        height="100%"
        row-key="id"
        empty-text="没有匹配的账号"
      >
        <template #toolbarButtons><Button size="sm" @click="createDialogVisible = true"><Plus />新建账号</Button></template>
        <template #identity="{ row }">
          <span class="users__identity">
            <span class="users__avatar" aria-hidden="true">{{ initial(row as unknown as AdminUserItem) }}</span>
            <span class="users__identity-text">
              <strong>{{ row.display_name || row.username }}</strong>
              <span class="users__account">@{{ row.username }}</span>
            </span>
          </span>
        </template>

        <template #email="{ row }">
          <span v-if="!row.email" class="users__dim">未绑定</span>
          <template v-else>
            <span>{{ row.email }}</span>
            <UiBadge v-if="row.email_verified_at" variant="ok" class="users__verified">已验证</UiBadge>
          </template>
        </template>

        <template #role="{ row }">
          <UiBadge :variant="tagVariant(roleTagType(row.role as string))">
            {{ roleLabel(row.role as string) }}
          </UiBadge>
        </template>

        <template #status="{ row }">
          <UiBadge :variant="tagVariant(statusTagType(row.status as string))" dot>
            {{ statusLabel(row.status as string) }}
          </UiBadge>
        </template>


        <template #tokens="{ row }">
          <span class="users__usage">
            {{ formatTokens((row.usage as { llm_tokens?: number })?.llm_tokens) }}
          </span>
        </template>

        <template #actions="{ row }">
          <RowActions :actions="rowActions(row as unknown as AdminUserItem)" :max-visible="1" />
        </template>
      </BasicTable>
    </div>

    <CreateUserDialog v-model="createDialogVisible" @created="reload" />
    <ResetPasswordDialog
      v-model:visible="resetPwdDialogVisible"
      :user="selectedUser"
      @saved="reload"
    />
    <NotifyUserDialog v-model:visible="notifyDialogVisible" :user="selectedUser" />
  </div>
</template>

<style scoped>
.users {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: var(--gap-3);
  min-width: 0;
  min-height: 0;
}

.users__head {
  padding-top: var(--gap-1);
  padding-bottom: 0;
}

.users__toolbar {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
}

.users__search {
  position: relative;
  flex: 1 1 240px;
  min-width: 0;
  max-width: 360px;
}

.users__search-icon {
  position: absolute;
  top: 50%;
  left: 9px;
  width: 14px;
  height: 14px;
  color: var(--text-tertiary);
  transform: translateY(-50%);
  pointer-events: none;
}

.users__search-input {
  padding-left: 28px;
}

.users__select {
  min-width: 112px;
}

.users__toolbar-actions {
  display: flex;
  align-items: center;
  gap: var(--gap-1);
  margin-left: auto;
}

.users__table {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-xs);
  overflow: hidden;
}

.users__identity {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-2);
  min-width: 0;
}

.users__avatar,
.user-card__avatar {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--seal-soft);
  color: var(--seal-ink);
  font-size: var(--fs-aux);
  font-weight: 600;
}

.users__identity-text {
  display: flex;
  flex-direction: column;
  gap: 0;
  min-width: 0;
  line-height: 1.25;
}

.users__identity-text strong {
  overflow: hidden;
  color: var(--text-primary);
  font-weight: 600;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.users__account,
.user-card__account {
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
}

.users__usage {
  color: var(--text-primary);
  font-family: var(--mono);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.users__dim {
  color: var(--text-tertiary);
}

.users__verified {
  margin-left: var(--gap-1);
}

/* ─── 手机卡列表 ─── */
.users__cards {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: var(--gap-2);
  min-height: 0;
  padding-bottom: var(--gap-6);
  overflow: auto;
  overscroll-behavior: contain;
}

.user-card {
  display: flex;
  align-items: flex-start;
  gap: var(--gap-3);
  padding: var(--gap-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-xs);
}

.user-card.is-disabled {
  opacity: 0.7;
}

.user-card__avatar {
  width: 36px;
  height: 36px;
  font-size: var(--fs-ui);
}

.user-card__body {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.user-card__top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.user-card__name {
  color: var(--text-primary);
  font-size: var(--fs-body);
  font-weight: 600;
}

.user-card__sub {
  display: flex;
  flex-wrap: wrap;
  gap: 2px var(--gap-2);
  margin: 0;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.user-card__email {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.user-card__usage {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  margin-top: 2px;
}

.user-card__bar {
  flex: 1 1 auto;
  height: 4px;
  border-radius: 2px;
  background: var(--surface-sunken);
  overflow: hidden;
}

.user-card__bar i {
  display: block;
  height: 100%;
  border-radius: 2px;
  background: var(--seal);
}

.user-card__usage-text {
  flex: 0 0 auto;
  color: var(--text-primary);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.user-card__usage-text small {
  color: var(--text-tertiary);
  font-weight: 400;
}

.user-card__more {
  flex: 0 0 auto;
  margin: -4px -4px 0 0;
}

.users__more {
  align-self: center;
  min-height: 40px;
}

@media (max-width: 640px) {
  .users__toolbar-actions {
    width: 100%;
    margin-left: 0;
  }

  .users__toolbar-actions > :deep(button) {
    flex: 1 1 auto;
    min-height: 40px;
  }

  .users__select {
    flex: 1 1 calc(50% - var(--gap-1));
  }
}
</style>
