<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { computed, onMounted, ref } from 'vue'
import { RefreshCw, UserRound } from '@lucide/vue'
import { toast } from 'vue-sonner'
import { getAuthMe, patchProfile } from '@/shared/api/auth'
import { useUserStore } from '@/shared/stores/user'
import type { AuthIdentity, UserSessionRecord } from '@/shared/types/auth'
import { toErrorMessage } from '@/shared/lib/errors'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Avatar, AvatarFallback, AvatarImage } from '@/shared/components/ui/avatar'
import { Button } from '@/shared/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/shared/components/ui/card'
import { Input } from '@/shared/components/ui/input'
import { Textarea } from '@/shared/components/ui/textarea'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import UiField from '@/shared/components/ui/UiField.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import AccountSecurityPane from './AccountSecurityPane.vue'
import MobilePageHeader from '@/shared/components/layout/MobilePageHeader.vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'

const mobile = useMobileLayout()
const mobileSection = ref('profile')

const userStore = useUserStore()
const user = computed(() => userStore.user)
const loading = ref(true)
const loadError = ref('')
const saving = ref(false)
const identities = ref<AuthIdentity[]>([])
const sessions = ref<UserSessionRecord[]>([])
const profile = ref({ username: '', display_name: '', avatar_url: '', bio: '' })
const initial = computed(() => (user.value?.display_name || user.value?.username || 'U').slice(0, 1))
let generation = 0

async function loadAccountData(): Promise<void> {
  const request = ++generation
  loading.value = true
  loadError.value = ''
  try {
    const me = await getAuthMe()
    if (request !== generation) return
    userStore.setUser(me.user)
    identities.value = me.identities || []
    sessions.value = me.sessions || []
    profile.value = { username: me.user.username || '', display_name: me.user.display_name || '', avatar_url: me.user.avatar_url || '', bio: me.user.bio || '' }
  } catch (error) {
    if (request === generation) loadError.value = toErrorMessage(error, '读取账号失败')
  } finally {
    if (request === generation) loading.value = false
  }
}
async function saveProfile(): Promise<void> {
  if (loading.value || loadError.value || saving.value || !userStore.canWrite) return
  saving.value = true
  try {
    const result = await patchProfile({ ...profile.value, username: profile.value.username || undefined })
    userStore.setUser(result)
    toast.success('个人资料已保存')
  } catch (error) { toast.error(toErrorMessage(error, '保存失败')) }
  finally { saving.value = false }
}
function passwordChanged(): void {
  if (userStore.user) userStore.user.must_change_password = false
  void loadAccountData()
}
onMounted(() => { void loadAccountData() })
</script>

<template>
  <div class="page-fill acct-page">
    <MobilePageHeader v-if="mobile" title="账户" :subtitle="user?.display_name || user?.username">
      <template #actions>
        <UiBadge v-if="user?.status" :variant="user.status === 'active' ? 'ok' : 'warn'" dot>{{ user.status === 'active' ? '正常' : '待激活' }}</UiBadge>
        <Button access="read" variant="ghost" size="icon" aria-label="刷新账户" :disabled="loading" @click="loadAccountData"><RefreshCw :class="{ 'animate-spin': loading }" /></Button>
      </template>
    </MobilePageHeader>
    <PageHeader v-else compact>
      <template #title>
        <Avatar class="acct-avatar"><AvatarImage v-if="user?.avatar_url" :src="user.avatar_url" alt="账号头像" /><AvatarFallback>{{ initial }}</AvatarFallback></Avatar>
        <span>{{ user?.display_name || user?.username || '账号设置' }}</span>
        <UiBadge variant="secondary">管理员</UiBadge>
        <UiBadge v-if="user?.status" :variant="user.status === 'active' ? 'ok' : 'warn'" dot>{{ user.status === 'active' ? '正常' : '待激活' }}</UiBadge>
      </template>
      <span class="acct-handle">@{{ user?.username || '—' }}</span>
      <template #actions><Button access="read" variant="outline" size="sm" :disabled="loading" @click="loadAccountData"><RefreshCw :class="{ 'animate-spin': loading }" />刷新</Button></template>
    </PageHeader>
    <PageTabs v-if="mobile" panel-id="account-mobile-panel" v-model="mobileSection" :items="[{ name:'profile', label:'个人资料' }, { name:'security', label:'密码与绑定' }, { name:'sessions', label:'登录设备' }]" variant="pill" :sticky="false" class="account-mobile-tabs" aria-label="账户设置分区" />
    <Alert v-if="loadError" variant="destructive" class="acct-error"><AlertTitle>{{ loadError }}</AlertTitle></Alert>
    <div id="account-mobile-panel" class="acct-body" :aria-busy="loading" :role="mobile ? 'tabpanel' : undefined" :tabindex="mobile ? 0 : undefined" :aria-labelledby="mobile ? `account-mobile-panel-tab-${mobileSection}` : undefined">
      <PageBusy overlay :busy="loading" label="读取账号…" />
      <AccountSecurityPane :mobile-section="mobile ? mobileSection : undefined" :user="user" :identities="identities" :sessions="sessions" :disabled="loading || Boolean(loadError)" @refresh="loadAccountData" @password-changed="passwordChanged">
        <template #profile>
          <Card class="acct-card">
            <CardHeader><CardTitle class="flex items-center gap-2"><UserRound class="size-4 text-mist" />个人资料</CardTitle></CardHeader>
            <form @submit.prevent="saveProfile">
              <CardContent class="acct-form">
                <UiField label="登录账号名"><Input v-model="profile.username" aria-label="登录账号名" autocomplete="username" maxlength="32" :disabled="loading || Boolean(loadError)" /></UiField>
                <UiField label="对外昵称"><Input v-model="profile.display_name" aria-label="对外昵称" autocomplete="nickname" maxlength="64" :disabled="loading || Boolean(loadError)" /></UiField>
                <UiField label="头像地址"><Input v-model="profile.avatar_url" aria-label="头像地址" inputmode="url" placeholder="https://…" :disabled="loading || Boolean(loadError)" /></UiField>
                <UiField label="个人简介"><Textarea v-model="profile.bio" aria-label="个人简介" rows="2" maxlength="500" placeholder="个人简介" :disabled="loading || Boolean(loadError)" /></UiField>
              </CardContent>
              <CardFooter class="acct-foot"><Button type="submit" size="sm" :disabled="saving || loading || Boolean(loadError)"><Spinner v-if="saving" class="animate-spin" />保存资料</Button></CardFooter>
            </form>
          </Card>
        </template>
      </AccountSecurityPane>
    </div>
  </div>
</template>
<style scoped src="./AccountView.css" />
