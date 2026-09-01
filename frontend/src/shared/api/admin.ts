import { apiRequest } from '@/shared/api/palace'
import type {
  AdminAuditResponse,
  AdminOverviewResponse,
  AdminUserItem,
  AdminUsersResponse,
  AuditLogItem,
  AdminAnnouncementItem,
  CreateAdminUserPayload,
  SetQuotaPayload,
  UpsertAnnouncementPayload,
} from '@/shared/types/admin'
import type { Role, UserQuota, UserStatus } from '@/shared/types/auth'

export async function getAdminOverview(): Promise<AdminOverviewResponse> {
  return apiRequest<AdminOverviewResponse>('/admin/overview')
}

export async function listAdminUsers(params?: {
  keyword?: string
  status?: string
  limit?: number
  offset?: number
}): Promise<AdminUsersResponse> {
  const query = new URLSearchParams()
  if (params?.keyword) query.set('keyword', params.keyword)
  if (params?.status) query.set('status', params.status)
  if (params?.limit !== undefined) query.set('limit', String(params.limit))
  if (params?.offset !== undefined) query.set('offset', String(params.offset))
  const qs = query.toString()
  return apiRequest<AdminUsersResponse>(`/admin/users${qs ? `?${qs}` : ''}`)
}

/** 管理员代建账号：本系统不开放自助注册，新号只能走这条路。 */
export async function createAdminUser(payload: CreateAdminUserPayload): Promise<AdminUserItem> {
  return apiRequest<AdminUserItem>('/admin/users', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function setUserRole(userId: string, role: Role): Promise<AdminUserItem> {
  return apiRequest<AdminUserItem>(`/admin/users/${encodeURIComponent(userId)}/role`, {
    method: 'PUT',
    body: JSON.stringify({ role }),
  })
}

export async function setUserStatus(userId: string, status: UserStatus): Promise<AdminUserItem> {
  return apiRequest<AdminUserItem>(`/admin/users/${encodeURIComponent(userId)}/status`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  })
}

export async function setUserQuota(userId: string, limits: SetQuotaPayload): Promise<UserQuota> {
  return apiRequest<UserQuota>(`/admin/users/${encodeURIComponent(userId)}/quota`, {
    method: 'PUT',
    body: JSON.stringify(limits),
  })
}

export async function resetUserPassword(
  userId: string,
  newPassword: string,
): Promise<{ ok: boolean }> {
  return apiRequest<{ ok: boolean }>(`/admin/users/${encodeURIComponent(userId)}/password`, {
    method: 'POST',
    body: JSON.stringify({ new_password: newPassword }),
  })
}

export async function notifyUser(
  userId: string,
  title: string,
  body = '',
): Promise<{ id: string }> {
  const query = new URLSearchParams({ title, body })
  return apiRequest<{ id: string }>(
    `/admin/users/${encodeURIComponent(userId)}/notify?${query.toString()}`,
    {
      method: 'POST',
    },
  )
}

/** 审计与登录日志的公共查询形状：两条流的行结构、筛选维度、倒序口径完全一致。 */
export interface AdminLogQuery {
  keyword?: string
  action?: string
  outcome?: string
  limit?: number
  offset?: number
}

function logQuery(params: AdminLogQuery | undefined, withAction: boolean): string {
  const query = new URLSearchParams()
  if (params?.keyword) query.set('keyword', params.keyword)
  if (withAction && params?.action) query.set('action', params.action)
  if (params?.outcome) query.set('outcome', params.outcome)
  if (params?.limit !== undefined) query.set('limit', String(params.limit))
  if (params?.offset !== undefined) query.set('offset', String(params.offset))
  const qs = query.toString()
  return qs ? `?${qs}` : ''
}

export async function listAdminAudit(params?: AdminLogQuery): Promise<AdminAuditResponse> {
  return apiRequest<AdminAuditResponse>(`/admin/audit${logQuery(params, true)}`)
}

/** 登录日志 = 审计流里的登录类事件，后端按 action 白名单收窄，行结构不变。 */
export async function listAdminLogins(params?: AdminLogQuery): Promise<AdminAuditResponse> {
  return apiRequest<AdminAuditResponse>(`/admin/logins${logQuery(params, false)}`)
}

export async function listAdminAnnouncements(): Promise<{ items: AdminAnnouncementItem[] }> {
  return apiRequest<{ items: AdminAnnouncementItem[] }>('/admin/announcements')
}

export async function upsertAdminAnnouncement(
  payload: UpsertAnnouncementPayload,
): Promise<{ id: string }> {
  return apiRequest<{ id: string }>('/admin/announcements', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function deleteAdminAnnouncement(announcementId: string): Promise<{ ok: boolean }> {
  return apiRequest<{ ok: boolean }>(`/admin/announcements/${encodeURIComponent(announcementId)}`, {
    method: 'DELETE',
  })
}
