<script setup lang="ts">
/*
 * 顶栏，定高 40px。
 *
 * 这里承担**全屏唯一**的会话级声明（「已收盘·展示最近快照」这类）。旧版把它
 * 同时放在顶栏胶囊、跑马灯、指数空态、四个榜单和信号流里，一屏七遍。现在文案
 * 由 lib/sessionCopy.ts 统一产出，且只有这一枚胶囊消费它。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Back, FullScreen, Moon, RefreshRight } from '@element-plus/icons-vue'
import { BRAND_MARK, BRAND_NAME } from '@/shared/lib/brand'
import { describeSession } from '../lib/sessionCopy'
import type { ConnectionStatus } from '../composables/useLiveBoard'

const props = defineProps<{
  status: ConnectionStatus
  asOf: string
  sessionPhase: string
  isLive: boolean
  /** 链路正常但上游没喂数据；与 status 分开报，避免把数据源故障说成连接中断 */
  dataStale?: boolean
  /** 最近一帧行情距今毫秒；-1=还没喂过数据 */
  staleMs?: number
  /** 采集器最近一次失败原因；空串=数据源正常 */
  sourceError?: string
  /** 暗色盯盘是否开着。**默认关**：大屏不替用户改全局外观 */
  inkOn?: boolean
}>()

const emit = defineEmits<{ refresh: []; toggleInk: [] }>()

const router = useRouter()
const isFullscreen = ref(false)

const session = computed(() =>
  describeSession(
    props.status,
    props.isLive,
 props.sessionPhase,
    props.dataStale ?? false,
    props.sourceError ?? '',
  ),
)

/*
 * 中部时段小字与右侧胶囊都出自 describeSession。收盘时胶囊本身就以时段开头，
 * 两处并排读出来是「已收盘 19:07:59 … 已收盘·展示最近快照」——同一个词半行内两遍。
 *
 * 让**时段小字**让位而不是改胶囊文案：胶囊那句还要被 LiveEmptyState 的 verbose
 * 空态复用，那里没有时段小字作陪，把「已收盘」从句子里摘掉就没人交代为什么空了。
 */
const showPhase = computed(() => !session.value.text.includes(session.value.phase))

/*
 * 时钟走**本机秒针**，不再显示 as_of。
 *
 * 顶栏最大的那个数字原先是「最近一帧的服务端时间」：上游一挂、或者午休一到，
 * 它就永远停在 12:00:02——用户截图里的那根箭头正是指着它问「怎么不动」。
 * 盯盘大屏的时钟必须一直走：**时钟回答「现在几点」，快照时间回答「数据多旧」**，
 * 后者归状态栏（LiveStatusBar 的「快照 / 延迟」）。
 */
const clock = ref(clockText())

function clockText(): string {
  const now = new Date()
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
}

let clockTimer: number | null = null

/** 落后多久：>1 个采集周期就在时钟旁挂一枚灰字，不用去底栏找 */
const lagText = computed<string>(() => {
  const ms = props.staleMs ?? -1
  if (!props.isLive || ms < 0) return ''
  const seconds = Math.round(ms / 1000)
  if (seconds < 10) return ''
  return seconds < 60 ? `延迟 ${seconds}s` : `延迟 ${Math.round(seconds / 60)}min`
})

function toggleFullscreen(): void {
  if (typeof document === 'undefined') return
  if (!document.fullscreenElement) {
    void document.documentElement.requestFullscreen?.().catch(() => {})
  } else {
    void document.exitFullscreen?.().catch(() => {})
  }
}

async function leaveBoard(): Promise<void> {
  // 先退全屏再跳：带着全屏状态回工作台，侧栏与底栏会落在可视区之外
  if (typeof document !== 'undefined' && document.fullscreenElement) {
    await document.exitFullscreen?.().catch(() => {})
  }
  await router.push({ name: 'pulse' })
}

function handleFullscreenChange(): void {
  isFullscreen.value = Boolean(document.fullscreenElement)
}

onMounted(() => {
  if (typeof window !== 'undefined') {
    clockTimer = window.setInterval(() => {
      clock.value = clockText()
    }, 1000)
  }
  if (typeof document === 'undefined') return
  document.addEventListener('fullscreenchange', handleFullscreenChange)
})

onUnmounted(() => {
  if (clockTimer !== null) {
    clearInterval(clockTimer)
    clockTimer = null
  }
  if (typeof document === 'undefined') return
  document.removeEventListener('fullscreenchange', handleFullscreenChange)
})
</script>

<template>
  <header class="topbar flex w-full flex-none items-center justify-between gap-3">
    <div class="topbar__brand">
      <!-- 印章红只留给 logo：D1 明令它既不是品牌色也不是涨跌色 -->
      <span class="topbar__mark">{{ BRAND_MARK }}</span>
      <span class="topbar__name">{{ BRAND_NAME }}</span>
      <span class="topbar__tag">盯盘大屏</span>
    </div>

    <div class="topbar__center flex min-w-0 items-baseline gap-2">
      <span v-if="showPhase" class="topbar__phase">{{ session.phase }}</span>
      <time class="topbar__clock live-num" :datetime="clock" aria-label="本机时间">{{ clock }}</time>
      <span v-if="lagText" class="topbar__lag live-num">{{ lagText }}</span>
    </div>

    <div class="topbar__actions flex items-center gap-2">
      <!-- 全屏唯一的会话级声明 -->
      <span class="topbar__session" :class="`topbar__session--${session.tone}`" role="status">
        <i class="topbar__dot" aria-hidden="true" />
        {{ session.text }}
      </span>

      <el-button size="small" text class="topbar__btn" :icon="RefreshRight" @click="emit('refresh')">刷新</el-button>
      <el-tooltip
        :content="inkOn ? '恢复为你选的外观' : '仅本页切到墨黑，不改你的外观设置'"
        placement="bottom"
        :show-after="300"
      >
        <el-button
          size="small"
          text
          class="topbar__btn"
          :class="{ 'topbar__btn--on': inkOn }"
          :aria-pressed="Boolean(inkOn)"
          :icon="Moon"
          @click="emit('toggleInk')"
        >
          暗色
        </el-button>
      </el-tooltip>
      <el-button size="small" text class="topbar__btn" :icon="FullScreen" :aria-pressed="isFullscreen" @click="toggleFullscreen">
        {{ isFullscreen ? '退出全屏' : '全屏' }}
      </el-button>
      <el-button size="small" text class="topbar__btn" :icon="Back" @click="leaveBoard">返回</el-button>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  gap: var(--gap-3);
  min-height: var(--live-topbar-h);
  padding: var(--gap-1) var(--gap-3);
  background-color: var(--live-head);
  border-bottom: 1px solid var(--live-rule);
}

.topbar__brand {
  display: flex;
  align-items: baseline;
  gap: var(--gap-2);
  min-width: 0;
}

.topbar__mark {
  font-size: var(--fs-title);
  font-weight: 800;
  color: var(--stamp);
}

.topbar__name {
  font-size: var(--fs-aux);
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--live-text);
  white-space: nowrap;
}

.topbar__tag {
  padding: 0 4px;
  font-size: var(--fs-kicker);
  letter-spacing: 0.08em;
  color: var(--live-muted);
  background-color: var(--live-accent-soft);
  border-radius: var(--radius);
  white-space: nowrap;
}

.topbar__center {
  min-width: 0;
  flex-shrink: 0;
}

.topbar__clock {
  font-size: var(--fs-hero);
  font-weight: 700;
  color: var(--live-text);
  line-height: 1.2;
}

.topbar__phase,
.topbar__lag {
  color: var(--live-dim);
  font-size: var(--fs-kicker);
  white-space: nowrap;
}

.topbar__session {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-1);
  padding: 1px var(--gap-2);
  font-size: var(--fs-kicker);
  color: var(--live-muted);
  border: 1px solid var(--live-rule);
  border-radius: var(--radius);
  white-space: nowrap;
}

.topbar__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: var(--live-dim);
}

.topbar__session--live {
  color: var(--live-ok);
  border-color: color-mix(in oklab, var(--live-ok) 45%, transparent);
}

.topbar__session--live .topbar__dot {
  background-color: var(--live-ok);
}

.topbar__session--warn {
  color: var(--live-warn);
  border-color: color-mix(in oklab, var(--live-warn) 45%, transparent);
}

.topbar__session--warn .topbar__dot {
  background-color: var(--live-warn);
}

.topbar__btn.el-button {
  --el-button-text-color: var(--live-muted);
  --el-button-hover-text-color: var(--live-accent);
  --el-button-hover-bg-color: transparent;
  min-height: var(--ctl-h);
  padding: 0 var(--gap-1);
  font-size: var(--fs-kicker);
}

.topbar__btn.el-button:focus-visible {
  outline: 1px solid var(--live-accent);
  outline-offset: 1px;
}

/* 开着时用淡印章底把「当前生效」说清楚，不靠文案变形（「暗色」/「亮色」会读成两个功能） */
.topbar__btn--on.el-button {
  --el-button-text-color: var(--live-accent);
  background-color: var(--live-accent-soft);
}

@media (max-width: 1100px) {
  .topbar {
    flex-wrap: wrap;
    gap: var(--gap-1) var(--gap-2);
  }
  .topbar__center {
    margin-left: auto;
  }
  .topbar__actions {
    flex-wrap: wrap;
    justify-content: flex-end;
    min-width: 0;
  }
  .topbar__tag,
  .topbar__name {
    display: none;
  }
}
@media (max-width: 740px) {
  .topbar__actions { width: 100%; gap: var(--gap-1); }
  .topbar__session { flex: 1 1 100%; white-space: normal; }
}
</style>
