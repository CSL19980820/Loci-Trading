import type { Role, UserQuota, UserStatus } from '@/shared/types/auth'

export interface TopLlmUsageItem {
  user_id: string
  period: string
  metric: string
  value: number
  updated_at: string
}

export interface AuditLogItem {
  id: string
  occurred_at: string
  login_at?: string | null
  actor_id: string
  actor_name: string
  action: string
  target: string
  outcome: string
  detail_json: string
  ip: string
}

export interface AdminOverviewResponse {
  users: number
  admins: number
  top_llm_usage: TopLlmUsageItem[]
  recent_audit: AuditLogItem[]
  visitors: number
  tenants: string[]
}

export interface AdminUserUsage {
  llm_tokens?: number
  llm_calls?: number
  [key: string]: number | undefined
}

export interface AdminUserItem {
  id: string
  tenant_id: string
  username: string
  email: string
  display_name: string
  role: Role
  status: UserStatus
  avatar_url: string
  bio: string
  email_verified_at: string | null
  created_at: string
  updated_at: string
  last_login_at: string | null
  must_change_password: boolean
  quota: UserQuota
  usage: AdminUserUsage
}

export interface AdminUsersResponse {
  items: AdminUserItem[]
  total: number
}

/** 审计 / 登录日志共用的分页响应。`total` 是过滤后的总条数，不是当前页条数。 */
export interface AdminAuditResponse {
  items: AuditLogItem[]
  total: number
}

/** 管理员代建账号。本系统不开放自助注册，账号只能从这里进。 */
export interface CreateAdminUserPayload {
  username: string
  password: string
  display_name?: string
  email?: string
  role?: Role
  status?: Extract<UserStatus, 'active' | 'disabled'>
}
