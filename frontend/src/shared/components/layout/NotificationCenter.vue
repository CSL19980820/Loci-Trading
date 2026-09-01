<script setup lang="ts">
/**
 * 通知与全站公告的唯一消费方：一枚紧凑触发 chip（可选）+ 一个右侧抽屉。
 *
 * 在此之前，`getNotifications` / `markNotificationsRead` / `AnnouncementItem`
 * 三样东西在 api 层已经齐了，管理后台的写端也做完了，但前端**没有任何组件读它们**：
 * 管理员发的公告用户永远看不到，头像角标永远是 0。这个抽屉就是那个缺失的读端。
 *
 * 刻意不做成第 N 条顶栏横幅：壳里只有一条 26px 状态轨（App.vue 的 .status-rail），
 * 公告一律收进抽屉，轨上只留一枚带未读角标的入口。
 *
 * `trigger` 不传时本组件只有抽屉，由父级用 v-model 控制（UserAvatarMenu 就这么用）。
 */
import { Bell } from '@element-plus/icons-vue'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { useUserStore } from '@/shared/stores/user'
import type { AnnouncementItem, NotificationItem } from '@/shared/types/auth'

defineProps<{
  /** 渲染一枚 20px 高的触发 chip（状态轨用）；侧栏走「消息」菜单项直接 v-model 开抽屉 */
  trigger?: boolean
}>()

const open = defineModel<boolean>({ default: false })

const router = useRouter()
const userStore = useUserStore()

const notifications = computed<NotificationItem[]>(() => userStore.notifications)
const announcements = computed<AnnouncementItem[]>(() => userStore.announcements)
const unread = computed<number>(() => userStore.unread)
const loading = ref(false)
const tab = ref<'inbox' | 'board'>('inbox')

/** chip 只有一个图标，文案全靠 aria-label / tooltip 说清楚 */
const triggerLabel = computed(() =>
  unread.value > 0 ? `消息 · ${unread.value} 条未读` : '消息 · 无未读',
)

watch(open, async (isOpen) => {
  if (!isOpen) return
  loading.value = true
  try {
    await userStore.loadNotifications()
  } finally {
    loading.value = false
  }
  // 打开即已读：抽屉已经把标题和正文全展开了，再要求点一下「标记已读」
  // 只是在制造一次无意义的点击。
  await userStore.markRead()
})

function levelTag(level?: string): 'danger' | 'warning' | 'info' {
  if (level === 'critical') return 'danger'
  if (level === 'warning') return 'warning'
  return 'info'
}

function levelLabel(level?: string): string {
  if (level === 'critical') return '重要'
  if (level === 'warning') return '注意'
  return '公告'
}

/** 后端给的是 ISO 串；列表里只显示到分钟，秒对通知没有意义。 */
function stamp(raw?: string | null): string {
  if (!raw) return ''
  const at = new Date(raw)
  if (Number.isNaN(at.getTime())) return raw
  return at.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function follow(item: NotificationItem): Promise<void> {
  if (!item.link) return
  // 通知里的 link 只认站内路径（例如 /screen-history?run=xxx）。外链一律不跟，
  // 否则一条被污染的通知就能把用户带去任意站点。
  if (!item.link.startsWith('/') || item.link.startsWith('//')) return
  open.value = false
  await router.push(item.link)
}
</script>

<template>
  <el-tooltip v-if="trigger" :content="triggerLabel" placement="bottom-end" :show-after="200">
    <el-button link class="notify-chip" :aria-label="triggerLabel" @click="open = true">
      <!-- 角标一律用圆点：轨上 chip 只有 20px 高，数字角标会被 .status-rail 的 overflow 裁掉 -->
      <el-badge is-dot :hidden="unread <= 0" class="notify-chip__badge">
        <el-icon class="notify-chip__icon"><Bell /></el-icon>
      </el-badge>
      <span class="notify-chip__text">消息</span>
      <span v-if="unread > 0" class="notify-chip__num">{{ unread > 99 ? '99+' : unread }}</span>
    </el-button>
  </el-tooltip>

  <el-drawer
    v-model="open"
    title="消息"
    direction="rtl"
    size="380px"
    class="notify-drawer"
    append-to-body
  >
    <el-radio-group v-model="tab" size="small" class="notify-tabs">
      <el-radio-button value="inbox">
        我的通知<span v-if="notifications.length"> · {{ notifications.length }}</span>
      </el-radio-button>
      <el-radio-button value="board">
        全站公告<span v-if="announcements.length"> · {{ announcements.length }}</span>
      </el-radio-button>
    </el-radio-group>

    <div v-loading="loading" class="notify-body">
      <template v-if="tab === 'inbox'">
        <EmptyState
          v-if="!notifications.length"
          description="还没有通知"
          reason="选股 / 盘中监测跑出结果，或定时任务与管理员有话要说时，消息会出现在这里。"
        />
        <template v-else>
          <el-button
            v-for="item in notifications"
            :key="item.id"
            text
            native-type="button"
            class="notify-item"
            :class="{ 'notify-item--unread': !item.read_at, 'notify-item--link': !!item.link }"
            @click="follow(item)"
          >
            <span class="notify-row">
              <span class="notify-head">
                <span class="notify-title">{{ item.title }}</span>
                <span class="notify-time">{{ stamp(item.created_at) }}</span>
              </span>
              <span class="notify-text">{{ item.body }}</span>
            </span>
          </el-button>
        </template>
      </template>

      <template v-else>
        <EmptyState
          v-if="!announcements.length"
          description="暂无公告"
          reason="管理员发布全站公告后会显示在这里。"
        />
        <article v-for="item in announcements" v-else :key="item.id" class="notify-item">
          <div class="notify-head">
            <el-tag size="small" :type="levelTag(item.level)">{{ levelLabel(item.level) }}</el-tag>
            <span class="notify-title">{{ item.title }}</span>
            <span class="notify-time">{{ stamp(item.published_at) }}</span>
          </div>
          <p class="notify-text">{{ item.body }}</p>
        </article>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
/* —— 触发 chip：与状态轨上的其它 chip 同一尺寸（20px / 11px / 3px 圆角 / 1px 边） —— */
.notify-chip.el-button {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-1);
  flex: 0 0 auto;
  height: 20px;
  margin: 0;
  padding: 0 var(--gap-1);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  color: var(--muted);
  font-size: var(--fs-kicker);
  font-weight: 400;
}

/* EP 把默认插槽包一层 <span>：铃铛 / 文案 / 未读数之间的 gap 要落在那一层上 */
.notify-chip.el-button > :deep(span) {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-1);
}

.notify-chip.el-button:hover {
  border-color: var(--seal);
  color: var(--seal-ink);
  background: var(--sheet);
}

.notify-chip__icon {
  font-size: 15px;
}

.notify-chip :deep(.el-badge) {
  display: inline-flex;
  align-items: center;
  line-height: 1;
}

/* 未读角标用印章红：它是提醒，不是涨跌，也不是品牌色（D1） */
.notify-chip :deep(.el-badge__content.is-dot) {
  width: 6px;
  height: 6px;
  padding: 0;
  border: 0;
  background: var(--stamp);
}

.notify-chip__num {
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}

/* —— 抽屉本体 —— */
.notify-tabs {
  margin-bottom: var(--gap-3);
}

.notify-body {
  display: grid;
  gap: var(--gap-2);
  align-content: start;
  min-height: 6rem;
}

.notify-item {
  display: grid;
  gap: var(--gap-1);
  width: 100%;
  padding: var(--gap-2);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  color: var(--ink);
  font: inherit;
  text-align: left;
}

/*
 * 列表项是 el-button（AGENTS §3.3.1：可点条目不许用裸 button）。EP 会把默认插槽
 * 包一层 <span>，所以这里用 column flex 让那层 span 自己撑满，内部再自己排版。
 */
.notify-item.el-button {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  height: auto;
  margin: 0;
  white-space: normal;
  font-weight: 400;
}

.notify-item.el-button + .notify-item.el-button {
  margin-left: 0;
}

.notify-item.el-button:hover,
.notify-item.el-button:focus-visible {
  background: var(--sheet);
  color: var(--ink);
}

.notify-row {
  display: grid;
  gap: var(--gap-1);
  width: 100%;
}

.notify-item--link {
  cursor: pointer;
}

.notify-item--link:hover {
  border-color: var(--seal);
}

/* 未读靠左侧色条标示，而不是整块染色——整块染色在 10 条以上时非常吵 */
.notify-item--unread {
  box-shadow: inset 2px 0 0 var(--stamp);
}

.notify-head {
  display: flex;
  align-items: center;
  gap: var(--gap-1);
}

.notify-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-body);
  font-weight: 600;
}

.notify-time {
  flex-shrink: 0;
  color: var(--mist);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
}

.notify-text {
  margin: 0;
  color: var(--muted);
  font-size: var(--fs-aux);
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
