export type Role = 'admin' | 'visitor'
export type UserStatus = 'active' | 'pending' | 'disabled' | 'deleted'
export type ProviderFamily = 'local' | 'wechat' | 'qq' | 'mock'
export type LoginMode = 'redirect' | 'qrcode'
export type QrStatus = 'pending' | 'scanned' | 'confirmed' | 'consumed' | 'expired' | 'failed'

export interface UserProfile {
  id: string
  username: string
  display_name: string
  avatar_url: string
  bio: string
  role: Role
  created_at: string
  email?: string
  email_verified?: boolean
  status?: UserStatus
  tenant_id?: string
  view_tenant_id?: string
  read_only?: boolean
  last_login_at?: string | null
  must_change_password?: boolean
  has_password?: boolean
}

export interface AuthSessionResponse {
  authenticated: boolean
  username: string
  user: UserProfile | null
}

export interface ProviderOption {
  name: string
  family: ProviderFamily
  label: string
  mode: LoginMode
}

export interface AuthOptionsResponse {
  email_signup: boolean
  providers: ProviderOption[]
}

export interface AuthIdentity {
  id: string
  provider: string
  family: ProviderFamily
  subject: string
  display_name: string
  avatar_url: string
  created_at: string
  last_used_at: string | null
}

export interface UserQuota {
  llm_monthly_tokens: number
  llm_daily_calls: number
  strategy_slots: number
  publish_slots: number
  /** 自建定时任务条数上限；系统托管的选股/情报任务不占额度 */
  job_slots: number
  /** 私有目录（palace.db + ops.db + skills/ + 各类 runs/）软上限，MB */
  storage_mb: number
}

export interface UserSessionRecord {
  id: string
  ip: string
  user_agent: string
  created_at: string
  last_seen_at: string
  expires_at: string
  current?: boolean
}

export interface AuthMeResponse {
  user: UserProfile
  identities: AuthIdentity[]
  quota: UserQuota
  sessions: UserSessionRecord[]
  unread: number
}

export interface QrStartResult {
  state: string
  mode: LoginMode
  redirect_url?: string | null
  qr_image_url?: string | null
  qr_content?: string | null
  expires_in: number
}

export interface QrPollResult {
  status: QrStatus
  redirect_to?: string
  error?: string
}
