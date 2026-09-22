/**
 * 管理后台的枚举字典：**界面上不出现英文标识符**。
 *
 * 后端存的是 `admin.set_role` / `active` / `__primary__` 这类机器口径，
 * 之前各个 Tab 各写各的三元表达式（有的漏了 pending、有的直接把
 * `admin.set_role` 原样打进标记里），于是同一个状态在四个页面有四种写法。
 * 这里是唯一真相：**新增枚举先加到这，再在页面里用 `*Label` / `*_OPTIONS`**。
 *
 * 下拉选项与文案共用同一张表——「筛选框里写中文、表格里也写中文」因此是结构保证，
 * 不是靠人肉对齐。
 */
import type { Role, UserStatus } from '@/shared/types/auth'

export interface DictOption {
  label: string
  value: string
}

/** 从 `值 -> 中文` 的映射派生下拉选项，避免选项与文案两处各抄一份。 */
function toOptions(map: Readonly<Record<string, string>>): DictOption[] {
  return Object.entries(map).map(([value, label]) => ({ label, value }))
}

/** 未登记的机器码兜底：显示占位符而不是把英文原样漏出去。 */
const UNKNOWN = '—'

// ---- 标记色 --------------------------------------------------------------

/** `*TagType` 的返回值：后端语义色名，界面上再翻成 Badge 的变体。 */
export type TagTone = 'success' | 'danger' | 'warning' | 'info'

/** 本仓 `UiBadge` 的语义变体（D1：涨跌色只给价格，状态走 ok / warn / info / stamp）。 */
export type BadgeTone = 'ok' | 'warn' | 'info' | 'stamp' | 'secondary'

/**
 * 语义色名 → Badge 变体。**只此一张表**：四个 Tab 曾各自写三元表达式，
 * 同一状态在不同页出现过三种颜色。
 */
export function tagVariant(tone: TagTone | string | null | undefined): BadgeTone {
  if (tone === 'success') return 'ok'
  if (tone === 'danger') return 'stamp'
  if (tone === 'warning') return 'warn'
  if (tone === 'info') return 'info'
  return 'secondary'
}

// ---- 角色 ----------------------------------------------------------------

const ROLE_LABELS: Readonly<Record<string, string>> = {
  admin: '管理员',
  visitor: '只读访客',
}

export const ROLE_OPTIONS: readonly DictOption[] = toOptions(ROLE_LABELS)

export function roleLabel(role: Role | string | null | undefined): string {
  if (!role) return UNKNOWN
  return ROLE_LABELS[role] ?? UNKNOWN
}

/** 角色标记走中性信息色：印章红留给破坏性操作，不用来标身份。 */
export function roleTagType(role: Role | string | null | undefined): 'warning' | 'info' {
  return role === 'admin' ? 'warning' : 'info'
}

// ---- 账号状态 -------------------------------------------------------------

const STATUS_LABELS: Readonly<Record<string, string>> = {
  active: '正常',
  pending: '待激活',
  disabled: '已停用',
}

export const STATUS_OPTIONS: readonly DictOption[] = toOptions(STATUS_LABELS)

/** 新建账号只给「正常 / 已停用」：`pending` 是邮箱验证流的中间态，管理员建号不经过它。 */
export const CREATABLE_STATUS_OPTIONS: readonly DictOption[] = [
  { label: STATUS_LABELS.active, value: 'active' },
  { label: STATUS_LABELS.disabled, value: 'disabled' },
]

export function statusLabel(status: UserStatus | string | null | undefined): string {
  if (!status) return UNKNOWN
  return STATUS_LABELS[status] ?? UNKNOWN
}

export function statusTagType(
  status: UserStatus | string | null | undefined,
): 'success' | 'danger' | 'warning' {
  if (status === 'active') return 'success'
  if (status === 'disabled') return 'danger'
  return 'warning'
}

// ---- 审计结果 -------------------------------------------------------------

const OUTCOME_LABELS: Readonly<Record<string, string>> = {
  ok: '成功',
  failed: '失败',
}

export const OUTCOME_OPTIONS: readonly DictOption[] = toOptions(OUTCOME_LABELS)

export function outcomeLabel(outcome: string | null | undefined): string {
  if (!outcome) return UNKNOWN
  return OUTCOME_LABELS[outcome] ?? '异常'
}

export function outcomeTagType(outcome: string | null | undefined): 'success' | 'danger' {
  return outcome === 'ok' ? 'success' : 'danger'
}

// ---- 公告级别 -------------------------------------------------------------

const LEVEL_LABELS: Readonly<Record<string, string>> = {
  info: '通知',
  warn: '警告',
  critical: '严重',
}

export const LEVEL_OPTIONS: readonly DictOption[] = toOptions(LEVEL_LABELS)

export function levelLabel(level: string | null | undefined): string {
  if (!level) return LEVEL_LABELS.info
  return LEVEL_LABELS[level] ?? LEVEL_LABELS.info
}

export function levelTagType(level: string | null | undefined): 'danger' | 'warning' | 'info' {
  if (level === 'critical') return 'danger'
  if (level === 'warn') return 'warning'
  return 'info'
}

// ---- 审计动作 -------------------------------------------------------------

/**
 * 与后端 `write_audit(action=...)` 的调用点一一对应。
 * 新加一处 `write_audit` 就在这补一行——补漏了只会落到下面的兜底拼词，
 * 不会（也不允许）把英文 action 原样显示出去。
 */
const ACTION_LABELS: Readonly<Record<string, string>> = {
  'platform.seed_admin': '初始化管理员',
  'admin.create_user': '新增用户',
  'admin.set_role': '变更角色',
  'admin.set_status': '变更账号状态',
  'admin.set_quota': '调整配额',
  'admin.reset_password': '重置用户密码',
  'admin.announcement': '发布公告',
  'account.register': '注册账号',
  'account.verify_email': '验证邮箱',
  'account.login': '账号登录',
  'account.social_login': '第三方登录',
  'account.social_register': '第三方注册',
  'account.change_password': '修改密码',
  'account.reset_password': '找回密码',
  'account.create_api_key': '创建接口密钥',
}

/**
 * 历史遗留机器码。早期那支一次性重置口令的脚本把动作写成了 `account.admin_reset_password`，
 * 正式入口（`identity/application/platform.py`）写的是 `admin.reset_password`；
 * 存量审计行仍在库里，靠这张表译成中文。
 * **不进筛选下拉**：同一件事不该在下拉里出现两个选项。
 */
const LEGACY_ACTION_ALIASES: Readonly<Record<string, string>> = {
  'account.admin_reset_password': '重置用户密码',
}

/**
 * 兜底拼词表：把没登记的 `域.动作` 两段各查一次，拼成「运维·导出」这种读得懂的中文。
 * 后端加了 `write_audit` 而这里忘了补 `ACTION_LABELS` 时，界面退化的下限是**中文**，
 * 不是把 `ops.export` 漏到表格里。
 */
const ACTION_DOMAIN_LABELS: Readonly<Record<string, string>> = {
  platform: '平台',
  admin: '后台',
  account: '账号',
  ops: '运维',
}

const ACTION_VERB_LABELS: Readonly<Record<string, string>> = {
  login: '登录',
  logout: '退出登录',
  register: '注册',
  create: '新增',
  update: '修改',
  delete: '删除',
  export: '导出',
  announcement: '发布公告',
  change_password: '修改密码',
  reset_password: '重置密码',
  admin_reset_password: '重置密码',
  set_role: '变更角色',
  set_status: '变更账号状态',
  set_quota: '调整配额',
}

export const ACTION_OPTIONS: readonly DictOption[] = toOptions(ACTION_LABELS)

/** 登录日志只关心这两类事件；与后端 `platform.LOGIN_ACTIONS` 对齐。 */
export const LOGIN_ACTION_OPTIONS: readonly DictOption[] = [
  { label: ACTION_LABELS['account.login'], value: 'account.login' },
  { label: ACTION_LABELS['account.social_login'], value: 'account.social_login' },
]

/**
 * 动作转中文。四级兜底，**每一级都只吐中文**：
 * 正式字典 → 遗留别名 → 「域·动作」拼词 → 「未登记操作」。
 * 最后一级一旦出现在界面上，就是提醒来补 `ACTION_LABELS` 的信号；
 * 原始机器码只活在网络层与后端审计库里。
 */
export function actionLabel(action: string | null | undefined): string {
  if (!action) return UNKNOWN
  const mapped = ACTION_LABELS[action] ?? LEGACY_ACTION_ALIASES[action]
  if (mapped) return mapped
  const dot = action.indexOf('.')
  const domainText = dot > 0 ? ACTION_DOMAIN_LABELS[action.slice(0, dot)] : undefined
  const verbText = ACTION_VERB_LABELS[dot > 0 ? action.slice(dot + 1) : action]
  if (domainText && verbText) return `${domainText}·${verbText}`
  return verbText ?? '未登记操作'
}

// ---- 租户 ----------------------------------------------------------------

/**
 * 租户列只回答一个问题：**这人是不是踩在主租户的数据目录上**。
 *
 * `__primary__` 是主租户的内部代号（就是老的 `data/` 目录），其余租户 id 等于
 * 用户 id（`u_6726e529b597` 这种），逐行摆出来既读不出信息，也让一列全是乱码串。
 * 原始 id 运维时确实要用，所以收进 `tenantHint` 的 tooltip，不占列宽。
 */
export function tenantLabel(tenantId: string | null | undefined): string {
  const raw = (tenantId || '').trim()
  if (!raw) return UNKNOWN
  return raw === '__primary__' ? '主租户' : '独立租户'
}

/** 租户列的 tooltip：原始租户 id（数据目录名）。 */
export function tenantHint(tenantId: string | null | undefined): string {
  const raw = (tenantId || '').trim()
  return raw ? `数据目录：${raw}` : ''
}

// ---- 时间 ----------------------------------------------------------------

/** 日志时间统一「YYYY-MM-DD HH:mm:ss」：秒是排查登录异常的关键精度。 */
export function logTime(value: string | null | undefined): string {
  const raw = (value || '').trim()
  if (!raw) return UNKNOWN
  return raw
    .replace('T', ' ')
    .replace(/(\.\d+)?(Z|[+-]\d{2}:?\d{2})$/, '')
    .slice(0, 19)
}

/** 账号时间列只到分钟：注册/最后登录不需要秒级精度，省一列宽度。 */
export function accountTime(value: string | null | undefined, fallback = UNKNOWN): string {
  const raw = (value || '').trim()
  if (!raw) return fallback
  return logTime(raw).slice(0, 16)
}
