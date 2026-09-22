<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { Eye, EyeOff, Link2, LoaderCircle, MonitorSmartphone, Smartphone } from '@lucide/vue'
import { toast } from 'vue-sonner'

import { changePassword, revokeOtherSessions, unbindIdentity } from '@/shared/api/auth'
import { Button } from '@/shared/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/shared/components/ui/card'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Input } from '@/shared/components/ui/input'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import UiField from '@/shared/components/ui/UiField.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import type { AuthIdentity, UserProfile, UserSessionRecord } from '@/shared/types/auth'

/**
 * 安全设置：三张卡——修改密码 | 登录设备（并排）；第三方账号（满幅）。
 * 手机端全部单列，设备行 44px 触控高度。
 */
const props = defineProps<{
  user: UserProfile | null
  identities: AuthIdentity[]
  sessions: UserSessionRecord[]
  disabled?: boolean
  mobileSection?: string
}>()

const emit = defineEmits<{
  refresh: []
  passwordChanged: []
}>()

const passwordForm = ref<{
  old_password: string
  new_password: string
  confirm_password: string
}>({
  old_password: '',
  new_password: '',
  confirm_password: '',
})
const savingPassword = ref<boolean>(false)
const revokingSessions = ref<boolean>(false)

const revealed = reactive({ old: false, new: false, confirm: false })

const passwordStrength = computed(() => {
  const p = passwordForm.value.new_password
  if (!p) return { text: '', color: '' }
  if (p.length < 8) return { text: '太短（至少 8 位）', color: 'var(--warn-ink)' }
  if (p.length < 12) return { text: '适中', color: 'var(--info-ink)' }
  return { text: '很好', color: 'var(--seal-ink)' }
})

const otherSessions = computed(() => props.sessions.filter((s) => !s.current).length)

function toMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback
}

function isMobileAgent(ua: string): boolean {
  return /iphone|android|mobile|ipad/i.test(ua)
}

function clientLabel(ua = ''): string {
  const os = /Windows/.test(ua) ? 'Windows' : /iPhone|iPad/.test(ua) ? 'iOS' : /Android/.test(ua) ? 'Android' : /Macintosh/.test(ua) ? 'macOS' : /Linux/.test(ua) ? 'Linux' : '未知系统'
  const browser = /Edg\//.test(ua) ? 'Edge' : /Chrome\//.test(ua) ? 'Chrome' : /Firefox\//.test(ua) ? 'Firefox' : /Safari\//.test(ua) ? 'Safari' : '浏览器'
  return `${os} · ${browser}`
}

function timeLabel(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? (value || '—') : new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
}

async function handleChangePassword(): Promise<void> {
  if (props.disabled || savingPassword.value) return
  const { old_password, new_password, confirm_password } = passwordForm.value
  if (!new_password || new_password.length < 8) {
    toast.warning('新密码长度不能少于 8 位')
    return
  }
  if (new_password !== confirm_password) {
    toast.warning('两次输入的新密码不一致')
    return
  }
  savingPassword.value = true
  try {
    await changePassword({ old_password, new_password })
    toast.success('密码修改成功')
    passwordForm.value = { old_password: '', new_password: '', confirm_password: '' }
    emit('passwordChanged')
  } catch (err: unknown) {
    toast.error(toMessage(err, '修改密码失败'))
  } finally {
    savingPassword.value = false
  }
}

async function handleRevokeOtherSessions(): Promise<void> {
  const confirmed = await confirmDangerous(
    '确定要下线其他所有设备与登录会话吗？',
    '下线其他设备',
    '确定下线',
  )
  if (!confirmed) return

  revokingSessions.value = true
  try {
    const res = await revokeOtherSessions()
    toast.success(`已下线 ${res.revoked} 个其他会话`)
    emit('refresh')
  } catch (err: unknown) {
    toast.error(toMessage(err, '操作失败'))
  } finally {
    revokingSessions.value = false
  }
}

async function handleUnbind(identity: AuthIdentity): Promise<void> {
  const confirmed = await confirmDangerous(
    `确定要解绑 ${identity.display_name || identity.provider} 吗？`,
    '解绑提示',
    '确定解绑',
  )
  if (!confirmed) return

  try {
    await unbindIdentity(identity.id)
    toast.success('解绑成功')
    emit('refresh')
  } catch (err: unknown) {
    toast.error(toMessage(err, '解绑失败'))
  }
}
</script>

<template>
  <div class="security-pane">
    <div class="sec-grid">
      <div v-show="!mobileSection || mobileSection !== 'sessions'" class="sec-main">
      <div v-show="!mobileSection || mobileSection === 'profile'" class="sec-profile"><slot name="profile" /></div>
      <!-- 修改密码 -->
      <Card v-show="!mobileSection || mobileSection === 'security'" class="sec-card">
        <CardHeader class="border-b">
          <CardTitle>修改密码</CardTitle>
          <CardDescription>{{ user?.has_password ? '需要先验证当前密码；至少 8 位，越长越安全' : '首次设置密码后即可用账号密码登录' }}</CardDescription>
        </CardHeader>
        <form @submit.prevent="handleChangePassword">
          <fieldset :disabled="disabled || savingPassword">
          <CardContent class="sec-fields">
            <UiField v-if="user?.has_password" label="原密码">
              <div class="relative">
                <Input
                  v-model="passwordForm.old_password"
                  :type="revealed.old ? 'text' : 'password'"
                  class="pr-10"
                  placeholder="输入当前密码"
                  autocomplete="current-password"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  class="password-reveal"
                  :aria-label="revealed.old ? '隐藏原密码' : '显示原密码'"
                  :aria-pressed="revealed.old"
                  @click="revealed.old = !revealed.old"
                >
                  <EyeOff v-if="revealed.old" class="size-3.5" aria-hidden="true" />
                  <Eye v-else class="size-3.5" aria-hidden="true" />
                </Button>
              </div>
            </UiField>

            <UiField label="新密码">
              <div class="relative">
                <Input
                  v-model="passwordForm.new_password"
                  :type="revealed.new ? 'text' : 'password'"
                  class="pr-10"
                  placeholder="至少 8 位新密码"
                  autocomplete="new-password"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  class="password-reveal"
                  :aria-label="revealed.new ? '隐藏新密码' : '显示新密码'"
                  :aria-pressed="revealed.new"
                  @click="revealed.new = !revealed.new"
                >
                  <EyeOff v-if="revealed.new" class="size-3.5" aria-hidden="true" />
                  <Eye v-else class="size-3.5" aria-hidden="true" />
                </Button>
              </div>
              <p v-if="passwordForm.new_password" class="sec-strength" :style="{ color: passwordStrength.color }">
                密码强度：{{ passwordStrength.text }}
              </p>
            </UiField>

            <UiField label="确认新密码">
              <div class="relative">
                <Input
                  v-model="passwordForm.confirm_password"
                  :type="revealed.confirm ? 'text' : 'password'"
                  class="pr-10"
                  placeholder="再次输入新密码"
                  autocomplete="new-password"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  class="password-reveal"
                  :aria-label="revealed.confirm ? '隐藏确认新密码' : '显示确认新密码'"
                  :aria-pressed="revealed.confirm"
                  @click="revealed.confirm = !revealed.confirm"
                >
                  <EyeOff v-if="revealed.confirm" class="size-3.5" aria-hidden="true" />
                  <Eye v-else class="size-3.5" aria-hidden="true" />
                </Button>
              </div>
            </UiField>
          </CardContent>
          <CardFooter class="sec-card__foot">
            <Button type="submit" :disabled="savingPassword || disabled">
              <LoaderCircle v-if="savingPassword" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
              更新密码
            </Button>
          </CardFooter>
          </fieldset>
        </form>
      </Card>
      </div>

      <!-- 登录设备 / 会话 -->
      <Card v-show="!mobileSection || mobileSection === 'sessions'" class="sec-card sec-sessions">
        <CardHeader class="border-b">
          <CardTitle>登录设备</CardTitle>
          <CardDescription>{{ sessions.length ? `${sessions.length} 个活跃会话` : '还没有记录到登录会话' }}</CardDescription>
          <CardAction>
            <Button
              variant="outline"
              size="sm"
              class="text-stamp"
              :disabled="revokingSessions || !otherSessions"
              @click="handleRevokeOtherSessions"
            >
              <LoaderCircle v-if="revokingSessions" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
              下线其他会话
            </Button>
          </CardAction>
        </CardHeader>
        <EmptyState v-if="sessions.length === 0" class="sec-empty" description="暂无登录设备" :icon="MonitorSmartphone" />
        <ul v-else class="sec-list" aria-label="登录设备">
          <li v-for="s in sessions" :key="s.id" class="sec-row">
            <span class="sec-row__icon">
              <Smartphone v-if="isMobileAgent(s.user_agent || '')" aria-hidden="true" />
              <MonitorSmartphone v-else aria-hidden="true" />
            </span>
            <span class="sec-row__main">
              <span class="sec-row__title">
                <span class="sec-mono">{{ s.ip || '未知 IP' }}</span>
                <UiBadge v-if="s.current" variant="ok" dot>当前设备</UiBadge>
              </span>
              <span class="sec-row__sub" :title="s.user_agent">{{ clientLabel(s.user_agent) }}</span>
            </span>
            <span class="sec-row__meta sec-mono">{{ timeLabel(s.last_seen_at || s.created_at) }}</span>
          </li>
        </ul>
      </Card>
    </div>

    <!-- 第三方绑定 -->
    <Card v-if="identities.length" v-show="!mobileSection || mobileSection === 'security'" class="sec-card sec-bindings">
      <CardHeader class="border-b">
        <CardTitle>第三方账号</CardTitle>
        <CardDescription>{{ identities.length ? `已绑定 ${identities.length} 个，可用于扫码登录` : '当前版本暂不支持自助绑定' }}</CardDescription>
      </CardHeader>
      <EmptyState
        v-if="identities.length === 0"
        class="sec-empty"
        description="还没绑定第三方账号"
        reason="当前版本暂不支持自助绑定"
        :icon="Link2"
      />
      <ul v-else class="sec-list" aria-label="第三方账号">
        <li v-for="idItem in identities" :key="idItem.id" class="sec-row">
          <span class="sec-row__icon"><Link2 aria-hidden="true" /></span>
          <span class="sec-row__main">
            <span class="sec-row__title">
              <span class="sec-provider">{{ idItem.provider }}</span>
              <span class="sec-row__name">{{ idItem.display_name || idItem.subject }}</span>
            </span>
            <span class="sec-row__sub sec-mono">绑定于 {{ idItem.created_at }}</span>
          </span>
          <Button variant="ghost" size="sm" class="text-stamp" @click="handleUnbind(idItem)">解绑</Button>
        </li>
      </ul>
    </Card>
  </div>
</template>

<style scoped src="./AccountSecurityPane.css" />
