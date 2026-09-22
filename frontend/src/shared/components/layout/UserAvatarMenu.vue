<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Brush, ChevronsUpDown, LogOut, Settings, ShieldCheck, User } from '@lucide/vue'
import { toast } from 'vue-sonner'

import { Avatar, AvatarFallback, AvatarImage } from '@/shared/components/ui/avatar'
import { Button } from '@/shared/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import { toErrorMessage } from '@/shared/lib/errors'
import { useUserStore } from '@/shared/stores/user'

const props = defineProps<{
  collapsed?: boolean
}>()

const emit = defineEmits<{ theme: []; navigate: [] }>()
const router = useRouter()
const menuOpen = ref(false)
const userStore = useUserStore()

const user = computed(() => userStore.user)
const isAdmin = computed(() => userStore.isAdmin)
const displayName = computed(() => user.value?.display_name || user.value?.username || '未登录')
const roleText = computed(() => (isAdmin.value ? '管理员' : user.value ? '访客' : ''))
const handleText = computed(() => (user.value?.username ? `@${user.value.username}` : ''))

const avatarText = computed(() => {
  const name = user.value?.display_name || user.value?.username || 'U'
  return name.slice(0, 1).toUpperCase()
})

async function onCommand(cmd: string): Promise<void> {
  menuOpen.value = false
  await nextTick()
  if (cmd === 'theme') {
    emit('theme')
  } else if (cmd === 'settings' && isAdmin.value) {
    await router.push('/ops')
    emit('navigate')
  } else if (cmd === 'account' && isAdmin.value) {
    await router.push('/account')
    emit('navigate')
  } else if (cmd === 'admin' && isAdmin.value) {
    await router.push('/admin')
    emit('navigate')
  } else if (cmd === 'logout') {
    try {
      await userStore.logout()
      toast.success('已安全退出')
    } catch (caught: unknown) {
      // 服务端可能已经把会话作废了；本地状态 logout() 的 finally 里已清干净，所以照样跳登录页。
      toast.warning(toErrorMessage(caught, '退出请求没送达，本地登录状态已清除'))
    }
    window.location.assign('/login')
  }
}
</script>

<template>
  <div class="user-menu-wrap w-full" :class="{ 'user-menu-wrap--collapsed': collapsed }">
    <DropdownMenu v-model:open="menuOpen" :modal="false">
      <DropdownMenuTrigger as-child>
        <Button access="read"
          variant="ghost"
          class="user-profile-btn"
          :class="{ 'user-profile-btn--collapsed': collapsed }"
          :title="collapsed ? displayName : undefined"
          :aria-label="`账号菜单：${displayName}`"
        >
          <span class="avatar-badge">
            <Avatar class="user-avatar">
              <AvatarImage v-if="user?.avatar_url" :src="user.avatar_url" :alt="displayName" />
              <AvatarFallback class="user-avatar__fallback">{{ avatarText }}</AvatarFallback>
            </Avatar>
          </span>

          <span v-if="!collapsed" class="user-meta">
            <span class="user-name" :title="displayName">{{ displayName }}</span>
            <span class="user-handle">{{ handleText || roleText || '点击登录' }}</span>
          </span>
          <ChevronsUpDown v-if="!collapsed" class="user-chevron" aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent side="top" align="start" class="user-dropdown-menu">
        <DropdownMenuLabel class="menu-user-header">
          <div class="menu-user-name">{{ displayName }}</div>
          <div class="menu-user-handle">
            <span v-if="handleText">{{ handleText }}</span>
            <span v-if="roleText" class="menu-user-role">{{ roleText }}</span>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem v-if="isAdmin" @select="() => void onCommand('account')">
          <User aria-hidden="true" />
          账号设置
        </DropdownMenuItem>
        <DropdownMenuItem access="read" @select="() => void onCommand('theme')"><Brush aria-hidden="true" />主题</DropdownMenuItem>
        <DropdownMenuItem v-if="isAdmin" @select="() => void onCommand('settings')"><Settings aria-hidden="true" />设置</DropdownMenuItem>
        <DropdownMenuItem v-if="isAdmin" @select="() => void onCommand('admin')">
          <ShieldCheck aria-hidden="true" />
          管理后台
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem access="read" @select="() => void onCommand('logout')">
          <LogOut aria-hidden="true" />
          退出登录
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  </div>
</template>

<style scoped>
.user-menu-wrap--collapsed {
  display: flex;
  justify-content: center;
}

/* 默认按钮是居中、定高的 inline-flex；这里要的是一条撑满侧栏的账号行 */
.user-profile-btn {
  width: 100%;
  height: auto;
  justify-content: flex-start;
  gap: 10px;
  padding: var(--gap-1) var(--gap-2);
  margin: 0;
  color: var(--text-primary);
}

.user-profile-btn--collapsed {
  justify-content: center;
  padding: var(--gap-1);
}

.avatar-badge {
  position: relative;
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
}

.user-avatar {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border-radius: 8px;
}

.user-avatar__fallback {
  border-radius: 8px;
  background: linear-gradient(150deg, var(--seal-soft), color-mix(in oklab, var(--seal) 28%, transparent));
  color: var(--seal-ink);
  font-weight: 600;
  font-size: var(--fs-aux);
}

.user-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  flex: 1 1 auto;
  min-width: 0;
  line-height: 1.2;
  text-align: left;
}

.user-name {
  max-width: 100%;
  overflow: hidden;
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 600;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.user-handle {
  max-width: 100%;
  overflow: hidden;
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
  font-weight: 400;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.user-chevron {
  flex-shrink: 0;
  width: 14px;
  height: 14px;
  color: var(--text-tertiary);
}

.user-dropdown-menu {
  min-width: 220px;
}

.menu-user-header {
  display: block;
  padding: var(--gap-2) var(--gap-2) var(--gap-1);
}

.menu-user-name {
  max-width: 24em;
  overflow-wrap: anywhere;
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 600;
}

.menu-user-handle {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  max-width: 24em;
  margin-top: 2px;
  overflow-wrap: anywhere;
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-weight: 400;
}

.menu-user-role {
  padding: 0 6px;
  border-radius: 999px;
  background: var(--seal-soft);
  color: var(--seal-ink);
  font-family: var(--font);
  font-weight: 500;
  line-height: 1.6;
}
</style>
