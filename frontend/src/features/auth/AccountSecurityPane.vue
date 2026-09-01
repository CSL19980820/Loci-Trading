<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { changePassword, revokeOtherSessions, unbindIdentity } from '@/shared/api/auth'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import type { AuthIdentity, UserProfile, UserSessionRecord } from '@/shared/types/auth'

const props = defineProps<{
  user: UserProfile | null
  identities: AuthIdentity[]
  sessions: UserSessionRecord[]
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

const passwordStrength = computed(() => {
  const p = passwordForm.value.new_password
  if (!p) return { text: '', color: '' }
  if (p.length < 8) return { text: '太短（至少 8 位）', color: 'var(--warn)' }
  if (p.length < 12) return { text: '适中', color: 'var(--info)' }
  return { text: '很好', color: 'var(--seal)' }
})

async function handleChangePassword(): Promise<void> {
  const { old_password, new_password, confirm_password } = passwordForm.value
  if (!new_password || new_password.length < 8) {
    ElMessage.warning('新密码长度不能少于 8 位')
    return
  }
  if (new_password !== confirm_password) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  savingPassword.value = true
  try {
    await changePassword({ old_password, new_password })
    ElMessage.success('密码修改成功')
    passwordForm.value = { old_password: '', new_password: '', confirm_password: '' }
    emit('passwordChanged')
  } catch (err: unknown) {
    ElMessage.error(err instanceof Error ? err.message : '修改密码失败')
  } finally {
    savingPassword.value = false
  }
}

async function handleRevokeOtherSessions(): Promise<void> {
  try {
    await ElMessageBox.confirm('确定要下线其他所有设备与登录会话吗？', '下线其他设备', {
      type: 'warning',
      confirmButtonText: '确定下线',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  revokingSessions.value = true
  try {
    const res = await revokeOtherSessions()
    ElMessage.success(`已下线 ${res.revoked} 个其他会话`)
    emit('refresh')
  } catch (err: unknown) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  } finally {
    revokingSessions.value = false
  }
}

async function handleUnbind(identity: AuthIdentity): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定要解绑 ${identity.display_name || identity.provider} 吗？`, '解绑提示', {
      type: 'warning',
      confirmButtonText: '确定解绑',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await unbindIdentity(identity.id)
    ElMessage.success('解绑成功')
    emit('refresh')
  } catch (err: unknown) {
    ElMessage.error(err instanceof Error ? err.message : '解绑失败')
  }
}
</script>

<template>
  <div class="security-pane">
    <!-- 修改密码 -->
    <section class="sec-section">
      <el-form label-position="top" class="form-max" @submit.prevent="handleChangePassword">
        <div class="sec-header-row">
          <h3 class="sec-title">修改密码</h3>
          <span
            v-if="passwordForm.new_password"
            class="sec-chip"
            :style="{ color: passwordStrength.color }"
          >{{ passwordStrength.text }}</span>
          <el-button type="primary" size="small" :loading="savingPassword" native-type="submit">
            更新密码
          </el-button>
        </div>
        <el-form-item v-if="user?.has_password" label="原密码">
          <el-input
            v-model="passwordForm.old_password"
            type="password"
            show-password
            placeholder="输入当前密码"
          />
        </el-form-item>

        <el-form-item label="新密码">
          <el-input
            v-model="passwordForm.new_password"
            type="password"
            show-password
            placeholder="至少 8 位新密码"
          />
        </el-form-item>

        <el-form-item label="确认新密码">
          <el-input
            v-model="passwordForm.confirm_password"
            type="password"
            show-password
            placeholder="再次输入新密码"
          />
        </el-form-item>
      </el-form>
    </section>

    <el-divider />

    <!-- 登录设备 / 会话 -->
    <section class="sec-section">
      <div class="sec-header-row">
        <h3 class="sec-title">登录设备</h3>
        <el-tag size="small" type="info" round>{{ sessions.length }}</el-tag>
        <el-button
          type="danger"
          plain
          size="small"
          :loading="revokingSessions"
          @click="handleRevokeOtherSessions"
        >
          下线其他会话
        </el-button>
      </div>

      <div class="session-list">
        <div v-for="s in sessions" :key="s.id" class="session-item">
          <div class="session-info">
            <div class="session-line">
              <span class="session-ip">{{ s.ip || '未知 IP' }}</span>
              <el-tag v-if="s.current" size="small" type="success" effect="plain">当前设备</el-tag>
            </div>
            <div class="session-ua">{{ s.user_agent || '未知客户端' }}</div>
            <div class="session-time">最近活跃：{{ s.last_seen_at || s.created_at }}</div>
          </div>
        </div>
      </div>
    </section>

    <el-divider />

    <!-- 第三方绑定 -->
    <section class="sec-section">
      <div class="sec-header-row">
        <h3 class="sec-title">第三方账号</h3>
        <el-tag size="small" type="info" round>{{ identities.length }}</el-tag>
      </div>
      <EmptyState v-if="identities.length === 0" description="还没绑定第三方账号" />
      <div v-else class="identity-list">
        <div v-for="idItem in identities" :key="idItem.id" class="identity-item">
          <div class="id-info">
            <span class="id-provider">{{ idItem.provider }}</span>
            <span class="id-name">{{ idItem.display_name || idItem.subject }}</span>
            <span class="id-time">绑定于 {{ idItem.created_at }}</span>
          </div>
          <el-button
            type="danger"
            text
            size="small"
            @click="handleUnbind(idItem)"
          >
            解绑
          </el-button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.form-max {
  max-width: 480px;
}

.sec-chip {
  font-size: 0.78rem;
  font-weight: 600;
}

.sec-section {
  padding: 0.5rem 0;
}

.sec-header-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.sec-header-row .el-button {
  margin-left: auto;
}

.sec-title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--ink);
}

.session-list,
.identity-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.session-item,
.identity-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  background: var(--panel-2);
  border: 1px solid var(--rule);
  border-radius: var(--radius-sm);
}

.session-line {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.session-ip {
  font-weight: 550;
  font-size: 0.9rem;
  color: var(--ink);
}

.session-ua {
  font-size: 0.78rem;
  color: var(--mist);
  margin-top: 0.2rem;
}

.session-time {
  font-size: 0.75rem;
  color: var(--mist);
  margin-top: 0.15rem;
}

.id-info {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.id-provider {
  font-weight: 600;
  text-transform: capitalize;
  color: var(--ink);
}

.id-name {
  font-size: 0.85rem;
  color: var(--ink-soft);
}

.id-time {
  font-size: 0.78rem;
  color: var(--mist);
}

</style>
