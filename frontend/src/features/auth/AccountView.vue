<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { CopyDocument } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  createApiKey,
  getAuthMe,
  listApiKeys,
  patchProfile,
  revokeApiKey,
} from '@/shared/api/auth'
import { copyText } from '@/shared/lib/clipboard'
import { useUserStore } from '@/shared/stores/user'
import type {
  ApiKeyItem,
  AuthIdentity,
  UserProfile,
  UserQuota,
  UserSessionRecord,
} from '@/shared/types/auth'
import StatCard from '@/shared/components/ui/StatCard.vue'
import AccountApiKeysPane from '@/features/auth/AccountApiKeysPane.vue'
import AccountSecurityPane from '@/features/auth/AccountSecurityPane.vue'

const userStore = useUserStore()

const activeTab = ref<'profile' | 'security' | 'quota' | 'apikeys'>('profile')
const loading = ref<boolean>(false)

const profileForm = ref<{
  username: string
  display_name: string
  avatar_url: string
  bio: string
}>({
  username: '',
  display_name: '',
  avatar_url: '',
  bio: '',
})
const savingProfile = ref<boolean>(false)

const identities = ref<AuthIdentity[]>([])
const sessions = ref<UserSessionRecord[]>([])
const quota = ref<UserQuota | null>(null)

const apiKeys = ref<ApiKeyItem[]>([])
const loadingKeys = ref<boolean>(false)
const createKeyDialogVisible = ref<boolean>(false)
const newKeyName = ref<string>('')
const newKeyScopes = ref<string>('read')
const creatingKey = ref<boolean>(false)
const newlyCreatedKey = ref<{ id: string; key: string } | null>(null)
const keySuccessDialogVisible = ref<boolean>(false)

const user = computed<UserProfile | null>(() => userStore.user)

function formatQuotaValue(val: number | undefined): string {
  // 「-」本身不说明任何事。读不到额度时说清是「还没拉到」而不是「没有额度」。
  if (val === undefined || val === null) return '读取中'
  if (val < 0) return '不限'
  if (val === 0) return '按系统默认'
  return val.toLocaleString()
}

function formatStorage(val: number | undefined): string {
  if (val === undefined || val === null) return '读取中'
  if (val < 0) return '不限'
  if (val === 0) return '按系统默认'
  if (val >= 1024) return `${(val / 1024).toFixed(val % 1024 === 0 ? 0 : 1)} GB`
  return `${val} MB`
}

/** 配额读数卡。表驱动，避免六张卡各写各的 label / 值 / 口径（原来缩进已经抄散架）。 */
const quotaCards = computed(() => [
  { label: '月 Tokens', value: formatQuotaValue(quota.value?.llm_monthly_tokens), hint: '' },
  { label: '日调用', value: formatQuotaValue(quota.value?.llm_daily_calls), hint: '' },
  { label: '策略槽位', value: formatQuotaValue(quota.value?.strategy_slots), hint: '' },
  { label: '发布槽位', value: formatQuotaValue(quota.value?.publish_slots), hint: '' },
  { label: '定时任务', value: formatQuotaValue(quota.value?.job_slots), hint: '托管任务不占额度' },
  { label: '目录容量', value: formatStorage(quota.value?.storage_mb), hint: '软上限，超限只加速清理' },
])

async function loadAccountData(): Promise<void> {
  loading.value = true
  try {
    const me = await getAuthMe()
    userStore.setUser(me.user)
    identities.value = me.identities || []
    sessions.value = me.sessions || []
    quota.value = me.quota

    profileForm.value = {
      username: me.user.username || '',
      display_name: me.user.display_name || '',
      avatar_url: me.user.avatar_url || '',
      bio: me.user.bio || '',
    }
  } catch (err: unknown) {
    ElMessage.error(err instanceof Error ? err.message : '加载账号信息失败')
  } finally {
    loading.value = false
  }
}

async function handleSaveProfile(): Promise<void> {
  savingProfile.value = true
  try {
    const updated = await patchProfile({
      username: profileForm.value.username || undefined,
      display_name: profileForm.value.display_name,
      avatar_url: profileForm.value.avatar_url,
      bio: profileForm.value.bio,
    })
    userStore.setUser(updated)
    ElMessage.success('个人资料已保存')
  } catch (err: unknown) {
    ElMessage.error(err instanceof Error ? err.message : '保存资料失败')
  } finally {
    savingProfile.value = false
  }
}

function onPasswordChanged(): void {
  if (userStore.user) {
    userStore.user.must_change_password = false
  }
}

async function fetchApiKeys(): Promise<void> {
  loadingKeys.value = true
  try {
    const res = await listApiKeys()
    apiKeys.value = res.items || []
  } catch (err: unknown) {
    ElMessage.error(err instanceof Error ? err.message : '加载 API Key 失败')
  } finally {
    loadingKeys.value = false
  }
}

async function handleCreateApiKey(): Promise<void> {
  if (!newKeyName.value.trim()) {
    ElMessage.warning('请输入 API Key 名称')
    return
  }
  creatingKey.value = true
  try {
    const res = await createApiKey({
      name: newKeyName.value.trim(),
      scopes: newKeyScopes.value,
    })
    newlyCreatedKey.value = res
    createKeyDialogVisible.value = false
    keySuccessDialogVisible.value = true
    newKeyName.value = ''
    await fetchApiKeys()
  } catch (err: unknown) {
    ElMessage.error(err instanceof Error ? err.message : '创建 API Key 失败')
  } finally {
    creatingKey.value = false
  }
}

async function handleRevokeApiKey(item: ApiKeyItem): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定要撤销「${item.name}」吗？撤销后立即失效且无法恢复。`, '撤销 API Key', {
      type: 'warning',
      confirmButtonText: '确定撤销',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await revokeApiKey(item.id)
    ElMessage.success('API Key 已撤销')
    await fetchApiKeys()
  } catch (err: unknown) {
    ElMessage.error(err instanceof Error ? err.message : '撤销失败')
  }
}

async function handleCopyText(text: string): Promise<void> {
  try {
    await copyText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败，请手动选择复制')
  }
}

onMounted(async () => {
  await loadAccountData()
  await fetchApiKeys()
})
</script>

<template>
  <div class="account-page page-fill">
    <div class="account-container page-scroll">
      <!-- 页面头部 -->
      <header class="account-header">
        <div class="user-summary">
          <el-avatar :size="56" :src="user?.avatar_url" class="user-avatar">
            {{ (user?.display_name || user?.username || 'U').slice(0, 1).toUpperCase() }}
          </el-avatar>
          <div class="user-info">
            <div class="user-title-row">
              <h1 class="user-name">{{ user?.display_name || user?.username }}</h1>
              <el-tag size="small" :type="user?.role === 'admin' ? 'danger' : 'info'" class="role-tag">
                {{ user?.role === 'admin' ? '管理员' : '成员' }}
              </el-tag>
              <el-tag v-if="user?.status" size="small" :type="user.status === 'active' ? 'success' : 'warning'">
                {{ user.status === 'active' ? '正常' : '待激活' }}
              </el-tag>
              <span class="user-sub">@{{ user?.username }} · {{ user?.email || '未绑定邮箱' }}</span>
            </div>
          </div>
        </div>
      </header>

      <!-- Tab 切换 -->
      <el-tabs v-model="activeTab" class="account-tabs">
        <!-- 1. 资料 -->
        <el-tab-pane label="个人资料" name="profile">
          <div class="tab-pane-content">
            <el-form label-position="top" class="form-max" @submit.prevent="handleSaveProfile">
              <el-form-item label="登录账号名">
                <el-input v-model="profileForm.username" placeholder="唯一登录账号" />
              </el-form-item>

              <el-form-item label="对外昵称">
                <el-input v-model="profileForm.display_name" placeholder="设置展示昵称" />
              </el-form-item>

              <el-form-item label="头像 URL">
                <el-input v-model="profileForm.avatar_url" placeholder="https://example.com/avatar.png" />
              </el-form-item>

              <el-form-item label="个人简介">
                <el-input
                  v-model="profileForm.bio"
                  type="textarea"
                  :rows="3"
                  placeholder="介绍一下你自己"
                />
              </el-form-item>

              <el-form-item>
                <el-button type="primary" :loading="savingProfile" native-type="submit">
                  保存资料
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>

        <!-- 2. 安全 -->
        <el-tab-pane label="安全设置" name="security">
          <AccountSecurityPane
            :user="user"
            :identities="identities"
            :sessions="sessions"
            @refresh="loadAccountData"
            @passwordChanged="onPasswordChanged"
          />
        </el-tab-pane>

        <!-- 3. 配额 -->
        <el-tab-pane label="资源配额" name="quota">
          <div class="tab-pane-content">
            <div class="quota-grid">
              <StatCard
                v-for="card in quotaCards"
                :key="card.label"
                :label="card.label"
                :value="card.value"
                :hint="card.hint"
              />
            </div>
          </div>
        </el-tab-pane>

        <!-- 4. 开放 API -->
        <el-tab-pane label="开放 API" name="apikeys">
          <AccountApiKeysPane
            :api-keys="apiKeys"
            :loading="loadingKeys"
            @create="createKeyDialogVisible = true"
            @revoke="handleRevokeApiKey"
          />
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 创建 API Key 弹窗 -->
    <el-dialog v-model="createKeyDialogVisible" title="新建 API Key" width="460px">
      <el-form label-position="top">
        <el-form-item label="Key 名称" required>
          <el-input v-model="newKeyName" placeholder="例如：my-trading-bot" autofocus />
        </el-form-item>
        <el-form-item label="权限范围">
          <el-select v-model="newKeyScopes" style="width: 100%">
            <el-option label="只读 (read)" value="read" />
            <el-option label="读写 (read,write)" value="read,write" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createKeyDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="creatingKey" @click="handleCreateApiKey">创建</el-button>
      </template>
    </el-dialog>

    <!-- Key 创建成功明文提示弹窗 -->
    <el-dialog
      v-model="keySuccessDialogVisible"
      title="API Key 创建成功"
      width="500px"
      :close-on-click-modal="false"
      :show-close="false"
    >
      <div class="key-success-body">
        <el-alert
          title="明文仅展示这一次，请立即复制保存"
          type="warning"
          show-icon
          :closable="false"
        />
        <div class="key-display-box">
          <code class="key-code">{{ newlyCreatedKey?.key }}</code>
          <el-button
            type="primary"
            :icon="CopyDocument"
            size="small"
            @click="handleCopyText(newlyCreatedKey?.key || '')"
          >
            复制
          </el-button>
        </div>
      </div>
      <template #footer>
        <el-button type="primary" @click="keySuccessDialogVisible = false">
          我已妥善保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* .page-fill 已给满高 flex 列；这里不再重复 height:100%，也不用 2rem 内边距垫白 */
.account-container {
  max-width: 72rem;
  width: 100%;
  margin: 0 auto;
}

.account-header {
  padding-bottom: var(--gap-2);
  border-bottom: 1px solid var(--rule);
}

.user-summary {
  display: flex;
  align-items: center;
  gap: var(--gap-3);
}

.user-avatar {
  background: var(--seal-soft);
  color: var(--seal-ink);
  font-weight: 600;
  font-size: var(--fs-hero);
}

.user-title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--gap-2);
}

/* D2：中文标题 17px / 700 / .03em，不换字族 */
.user-name {
  margin: 0;
  font-size: var(--fs-hero);
  font-weight: 700;
  letter-spacing: 0.03em;
  color: var(--ink);
}

.user-sub {
  margin: 0;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-aux);
  color: var(--mist);
}

.tab-pane-content {
  padding-top: var(--gap-2);
}

.form-max {
  max-width: 30rem;
}

/* auto-fill + minmax：卡片不足时不留硬空格 */
.quota-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(13rem, 1fr));
  align-items: start;
  gap: var(--gap-2);
}

.key-success-body {
  display: flex;
  flex-direction: column;
  gap: var(--gap-2);
}

.key-display-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
  padding: var(--gap-2) var(--gap-3);
  background: var(--sheet-alt);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
}

.key-code {
  font-family: var(--mono);
  font-size: var(--fs-body);
  color: var(--seal-ink);
  word-break: break-all;
}
</style>
