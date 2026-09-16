<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Bell, SwitchButton, Tools, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import NotificationCenter from '@/shared/components/layout/NotificationCenter.vue'
import { toErrorMessage } from '@/shared/lib/errors'
import { useUserStore } from '@/shared/stores/user'

const props = defineProps<{
  collapsed?: boolean
}>()

const router = useRouter()
const userStore = useUserStore()

const user = computed(() => userStore.user)
const unread = computed(() => userStore.unread)
const isAdmin = computed(() => userStore.isAdmin)
const displayName = computed(
  () => user.value?.display_name || user.value?.username || '未登录',
)

const avatarText = computed(() => {
  const name = user.value?.display_name || user.value?.username || 'U'
  return name.slice(0, 1).toUpperCase()
})

const notifyOpen = ref(false)

// 角标要在壳一挂载就有数，否则用户只有主动点开抽屉才知道有未读——
// 那就等于没有角标。这一枪打的是 /auth/notifications，不阻塞任何渲染。
onMounted(() => {
  void userStore.loadNotifications()
})

async function onCommand(cmd: string): Promise<void> {
  if (cmd === 'notifications') {
    notifyOpen.value = true
  } else if (cmd === 'account') {
    await router.push('/account')
  } else if (cmd === 'admin') {
    await router.push('/admin')
  } else if (cmd === 'logout') {
    try {
      await userStore.logout()
      ElMessage.success('已安全退出')
    } catch (caught: unknown) {
   // 服务端可能已经把会话作废了；本地状态 logout() 的 finally 里已清干净，
      // 所以照样跳登录页。只吞掉原因会让「退出失败」变成一句无法排查的死话。
    ElMessage.warning(toErrorMessage(caught, '退出请求没送达，本地登录状态已清除'))
    }
    await router.replace('/login')
  }
}
</script>

<template>
  <div class="user-menu-wrap w-full" :class="{ 'user-menu-wrap--collapsed': collapsed }">
    <el-dropdown trigger="click" placement="top-start" @command="onCommand">
      <!-- 触发器用 el-button text：焦点环 / 禁用态 / 主题联动全部跟 EP 走，不再手画 -->
      <el-button
        text
        class="user-profile-btn"
        :class="{ 'user-profile-btn--collapsed': collapsed }"
        :title="collapsed ? user?.display_name || user?.username : undefined"
        :aria-label="`账号菜单：${user?.display_name || user?.username || '未登录'}`"
      >
        <el-badge :value="unread" :hidden="unread <= 0" :max="99" class="avatar-badge">
          <el-avatar :size="28" :src="user?.avatar_url" class="user-avatar">
            {{ avatarText }}
          </el-avatar>
        </el-badge>

        <!--
        角色标签（管理员/成员）已删：侧栏只有 176px，标签一挂上名字就只剩三四个字，
          而「我是不是管理员」下拉里的「管理后台」一项已经交代了。
          名字过长走省略号 + title 悬停看全名，不换行也不挤压头像。
        -->
        <span v-if="!collapsed" class="user-meta">
          <span class="user-name" :title="displayName">{{ displayName }}</span>
        </span>
      </el-button>

      <template #dropdown>
        <el-dropdown-menu class="user-dropdown-menu">
          <div class="menu-user-header">
            <div class="menu-user-name">{{ user?.display_name || user?.username }}</div>
            <div class="menu-user-handle">@{{ user?.username }}</div>
          </div>
          <el-dropdown-item divided command="notifications" :icon="Bell">
            消息
            <span v-if="unread > 0" class="menu-unread">{{ unread > 99 ? '99+' : unread }}</span>
          </el-dropdown-item>
          <el-dropdown-item command="account" :icon="User">账号设置</el-dropdown-item>
          <el-dropdown-item v-if="isAdmin" command="admin" :icon="Tools">管理后台</el-dropdown-item>
          <el-dropdown-item divided command="logout" :icon="SwitchButton">退出登录</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>

  <NotificationCenter v-model="notifyOpen" />
</template>

<style scoped>
.user-menu-wrap {
  padding-top: var(--gap-1);
  border-top: 1px solid var(--rule);
}

.user-menu-wrap--collapsed {
  display: flex;
  justify-content: center;
}

/*
 * el-button 默认是居中、定高的 inline-flex；这里要的是一条撑满侧栏的账号行，
 * 所以只改布局三项（满宽 / 左对齐 / 高度随内容），配色与焦点环仍由 EP 的 text 变体给。
 */
.user-profile-btn {
  width: 100%;
  height: auto;
  justify-content: flex-start;
  padding: var(--gap-1) var(--gap-2);
  margin: 0;
  color: var(--ink);
}

/* EP 把默认插槽包了一层无类名的 span，撑开它内容才能左对齐 */
.user-profile-btn :deep(> span) {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  flex: 1 1 auto;
  min-width: 0;
}

.user-profile-btn--collapsed {
  justify-content: center;
  padding: var(--gap-1);
}

.user-profile-btn--collapsed :deep(> span) {
  flex: 0 0 auto;
  justify-content: center;
}

.avatar-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.user-avatar {
  background: var(--seal-soft);
  color: var(--seal-ink);
  font-weight: 600;
  font-size: var(--fs-aux);
  flex-shrink: 0;
}

.user-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-1);
  flex: 1 1 auto;
  min-width: 0;
}

.user-name {
  min-width: 0;
  font-size: var(--fs-body);
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--ink);
}

.menu-user-header {
  padding: var(--gap-1) var(--gap-3) 0;
}

.menu-user-name {
  overflow-wrap: anywhere;
  max-width: 24em;
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--ink);
}

.menu-user-handle {
  overflow-wrap: anywhere;
  max-width: 24em;
  font-family: var(--mono);
  font-size: var(--fs-aux);
  color: var(--mist);
}

/* 未读数是数字：等宽 + tabular-nums，两位数变三位时不横跳 */
.menu-unread {
  margin-left: auto;
  padding: 0 var(--gap-1);
  border-radius: 999px;
  background: var(--seal);
  color: var(--on-primary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-variant-numeric: tabular-nums;
  line-height: 1.5;
}
</style>
