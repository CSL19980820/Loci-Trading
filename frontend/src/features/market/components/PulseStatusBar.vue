<script setup lang="ts">
/**
 * 一行异常条：正常时父级不渲染它，出错也只占一行。
 * 全文进 popover——四条 el-alert 叠在页头把主内容顶下去的日子结束了。
 */
import { computed } from 'vue'

export interface PulseIssue {
  key: string
  /** 一句话标题（≤10 字），如「行情更新失败」 */
  label: string
  /** 原始报错全文，进 popover */
  detail: string
}

const props = defineProps<{
  issues: PulseIssue[]
  busy?: boolean
}>()

const emit = defineEmits<{
  retry: []
}>()

const headline = computed(() => {
  const first = props.issues[0]
  if (!first) return ''
  const count = props.issues.length
  return count > 1 ? `${count} 项异常 · ${first.label}` : first.label
})
</script>

<template>
  <div v-if="issues.length" class="pulse-issues" role="status">
    <span class="pulse-issues__mark" aria-hidden="true">!</span>
    <span class="pulse-issues__text">{{ headline }}</span>
    <el-popover placement="bottom-start" :width="380" trigger="click">
      <template #reference>
        <el-button link type="primary" size="small">查看</el-button>
      </template>
      <ul class="pulse-issues__list">
        <li v-for="issue in issues" :key="issue.key">
          <strong>{{ issue.label }}</strong>
          <span>{{ issue.detail }}</span>
        </li>
      </ul>
    </el-popover>
    <el-button link size="small" :loading="busy" @click="emit('retry')">重试</el-button>
  </div>
</template>

<style scoped>
.pulse-issues {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--gap-2, 8px);
  padding: 2px var(--gap-2, 8px);
  border-bottom: 1px solid var(--rule);
  background: var(--sheet-alt, var(--sheet));
  font-size: var(--fs-aux, 12px);
  color: var(--warn);
  min-width: 0;
}

.pulse-issues__mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 15px;
  height: 15px;
  border: 1px solid var(--warn);
  border-radius: 50%;
  font-family: var(--mono);
  /* 圆圈里的感叹号：跟着最小字阶走，不写死 px */
  font-size: var(--fs-kicker);
  line-height: 1;
  flex: 0 0 auto;
}

/* 两个 link 按钮压到 18px：异常条整体不超过 24px，出错也不许顶开主内容 */
.pulse-issues :deep(.el-button) {
  height: 18px;
  min-height: 18px;
  padding: 0 2px;
  font-size: var(--fs-aux, 12px);
}

.pulse-issues__text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pulse-issues__list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--gap-2, 8px);
}

.pulse-issues__list li {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.pulse-issues__list strong {
  font-size: var(--fs-aux, 12px);
  color: var(--ink);
}

.pulse-issues__list span {
  font-size: var(--fs-aux, 12px);
  color: var(--mist);
  word-break: break-all;
}
</style>
