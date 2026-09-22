import { apiRequest } from '@/shared/api/palace'
import type {
  AuthMeResponse,
  AuthOptionsResponse,
  AuthSessionResponse,
  QrPollResult,
  QrStartResult,
  UserProfile,
} from '@/shared/types/auth'

export async function getAuthOptions(): Promise<AuthOptionsResponse> {
  return apiRequest<AuthOptionsResponse>('/auth/options')
}

export async function loginWithPassword(
  username: string,
  password: string,
): Promise<{ authenticated: boolean; user: UserProfile }> {
  return apiRequest<{ authenticated: boolean; user: UserProfile }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

export async function registerWithEmail(payload: {
  email: string
  password: string
  username?: string
  display_name?: string
}): Promise<{ ok: boolean; message?: string; mail_delivered?: boolean }> {
  return apiRequest<{ ok: boolean; message?: string; mail_delivered?: boolean }>('/auth/register', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function verifyEmail(payload: {
  token?: string
  code?: string
  email?: string
}): Promise<{ authenticated: boolean; user: UserProfile }> {
  return apiRequest<{ authenticated: boolean; user: UserProfile }>('/auth/verify-email', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function resendVerificationCode(
  email: string,
): Promise<{ ok: boolean; message?: string }> {
  return apiRequest<{ ok: boolean; message?: string }>('/auth/resend-code', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

export async function requestForgotPassword(
  email: string,
): Promise<{ ok: boolean; message?: string }> {
  return apiRequest<{ ok: boolean; message?: string }>('/auth/forgot-password', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

export async function resetPassword(payload: {
  token?: string
  code?: string
  email?: string
  new_password: string
}): Promise<{ ok: boolean }> {
  return apiRequest<{ ok: boolean }>('/auth/reset-password', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function logout(): Promise<{ authenticated: boolean }> {
  return apiRequest<{ authenticated: boolean }>('/auth/logout', { method: 'POST' })
}

export async function getAuthSession(): Promise<AuthSessionResponse> {
  return apiRequest<AuthSessionResponse>('/auth/session')
}

export async function getAuthMe(): Promise<AuthMeResponse> {
  return apiRequest<AuthMeResponse>('/auth/me')
}

export async function patchProfile(payload: {
  display_name?: string
  bio?: string
  avatar_url?: string
  username?: string
}): Promise<UserProfile> {
  return apiRequest<UserProfile>('/auth/me', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function changePassword(payload: {
  old_password: string
  new_password: string
}): Promise<{ ok: boolean }> {
  return apiRequest<{ ok: boolean }>('/auth/me/password', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function revokeOtherSessions(): Promise<{ revoked: number }> {
  return apiRequest<{ revoked: number }>('/auth/me/sessions', { method: 'DELETE' })
}

export async function unbindIdentity(identityId: string): Promise<{ ok: boolean }> {
  return apiRequest<{ ok: boolean }>(`/auth/me/identities/${encodeURIComponent(identityId)}`, {
    method: 'DELETE',
  })
}

export async function startQrLogin(payload: {
  provider: string
  redirect_to?: string
}): Promise<QrStartResult> {
  return apiRequest<QrStartResult>('/auth/qr/start', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function pollQrState(state: string): Promise<QrPollResult> {
  return apiRequest<QrPollResult>(`/auth/qr/${encodeURIComponent(state)}`)
}

export async function markQrScanned(state: string): Promise<{ ok: boolean }> {
  return apiRequest<{ ok: boolean }>(`/auth/qr/${encodeURIComponent(state)}/scanned`, {
    method: 'POST',
  })
}

export async function claimQrSession(
  state: string,
): Promise<{ authenticated: boolean; user: UserProfile }> {
  return apiRequest<{ authenticated: boolean; user: UserProfile }>(
    `/auth/qr/${encodeURIComponent(state)}/claim`,
    {
      method: 'POST',
    },
  )
}

export async function confirmMockQr(payload: {
  state: string
  handle?: string
}): Promise<{ ok: boolean }> {
  return apiRequest<{ ok: boolean }>('/auth/mock/confirm', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
