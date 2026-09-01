<script setup lang="ts">
export type AssistantPromptCard = {
  id: string
  title: string
  hint: string
  prompt: string
}

withDefaults(defineProps<{
  prompts: AssistantPromptCard[]
  /** 忙态 / 未配模型时父级会静默丢弃 pick，按钮同步置灰而不是点了没反应 */
  busy?: boolean
  providerReady?: boolean
}>(), {
  busy: false,
  providerReady: true,
})

const emit = defineEmits<{ pick: [prompt: string] }>()
</script>

<template>
  <div class="assistant-empty" data-testid="assistant-empty">
    <div class="assistant-empty__brand">
      <svg class="assistant-empty__mark" viewBox="0 0 48 48" focusable="false" aria-hidden="true">
        <circle cx="24" cy="24" r="22" fill="var(--ai-disc-face)" />
        <g fill="none" stroke="var(--ai-disc-ribbon)" stroke-linecap="round" stroke-linejoin="round">
          <path stroke-width="2.2" d="M16.5 28.5 C17.8 18.5 24.5 15 29.5 19.5 C34.8 24.2 32.2 33.5 24.5 33.5 C19.5 33.5 16.2 30.8 16.5 28.5 Z" />
          <path stroke-width="1.7" opacity="0.72" d="M19.5 18.5 C24.5 22 28.2 26.8 26.8 32.2" />
        </g>
        <circle cx="24" cy="24" r="2.2" fill="var(--seal)" />
      </svg>
      <span class="assistant-empty__wordmark" aria-hidden="true">落点</span>
      <h3 class="assistant-empty__headline">今天想落在哪？</h3>
    </div>
    <p class="assistant-empty__sub">点一条范例，改完再发</p>
    <ul class="assistant-empty__list" role="list">
      <li v-for="card in prompts" :key="card.id" role="listitem">
        <el-button
          class="assistant-empty__row"
          :disabled="busy || !providerReady"
          :aria-label="card.title"
          @click="emit('pick', card.prompt)"
        >
          <span class="assistant-empty__row-title">{{ card.title }}</span>
          <span class="assistant-empty__row-hint">{{ card.hint }}</span>
        </el-button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.assistant-empty {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: .55rem;
  padding: 1rem 0 1.25rem;
  width: 100%;
  box-sizing: border-box;
  text-align: center;
}

.assistant-empty__brand {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: .7rem;
}

.assistant-empty__mark {
  width: 2.2rem;
  height: 2.2rem;
  display: block;
  flex: 0 0 auto;
}

.assistant-empty__wordmark {
  font-size: var(--ai-fs-title);
  font-weight: 700;
  letter-spacing: .18em;
  color: var(--ink);
}

.assistant-empty__headline {
  margin: 0;
  /* 原为 padding-left + border-left: 1px solid var(--rule)：纯装饰竖分隔已删，层级交给上方 gap */
  font-size: clamp(var(--ai-fs-title), 2.4vw, var(--fs-hero));
  font-weight: 650;
  letter-spacing: -.02em;
  color: var(--ink);
}

.assistant-empty__sub {
  margin: 0;
  color: var(--muted);
  font-size: var(--ai-fs-aux);
  line-height: 1.4;
}

.assistant-empty__list {
  list-style: none;
  margin: .55rem 0 0;
  padding: 0;
  width: min(100%, 44rem);
  display: flex;
  flex-direction: column;
  gap: var(--ai-gap-md);
  text-align: left;
}

/* 走 EP 变量而不是跟 .el-button:hover 拼特异性，换 EP 版本也不会被盖回去 */
.assistant-empty__row {
  --el-button-bg-color: var(--panel);
  --el-button-border-color: var(--rule);
  --el-button-text-color: var(--ink);
  --el-button-hover-bg-color: var(--seal-soft);
  --el-button-hover-border-color: color-mix(in srgb, var(--seal) 55%, var(--rule));
  --el-button-hover-text-color: var(--ink);
  display: flex !important;
  flex-direction: row;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
  width: 100%;
  height: auto !important;
  margin: 0 !important;
  padding: .55rem .85rem !important;
  border-radius: var(--ai-r-card);
  box-sizing: border-box;
  white-space: normal;
}

/* EP 把插槽裹进 span；不撑开就只有文字宽，两段文案挤在中间 */
.assistant-empty__row :deep(.el-button__content),
.assistant-empty__row :deep(> span) {
  display: flex;
  flex-direction: row;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
  width: 100%;
  min-width: 0;
}

.assistant-empty__row-title {
  flex: 0 0 auto;
  font-size: var(--ai-fs-body);
  font-weight: 650;
  line-height: 1.35;
  color: inherit;
  white-space: nowrap;
}

.assistant-empty__row-hint {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--mist);
  font-size: var(--ai-fs-aux);
  line-height: 1.35;
  font-weight: 400;
  text-align: right;
}
</style>
