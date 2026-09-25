<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import { Tabs, TabsList, TabsTrigger } from '@/shared/components/ui/tabs'
import { Textarea } from '@/shared/components/ui/textarea'
import { Button } from '@/shared/components/ui/button'
import { Label } from '@/shared/components/ui/label'

const prompt = defineModel<string>('prompt', { default: '' })
const common = defineModel<string>('commonPrompt', { default: '' })
const premarket = defineModel<string>('premarketPrompt', { default: '' })
const review = defineModel<string>('reviewPrompt', { default: '' })
const weekly = defineModel<string>('weeklyPrompt', { default: '' })
const props = withDefaults(defineProps<{ defaultPrompt?: string; defaultWeeklyPrompt?: string; separateWeekly?: boolean; maxLength?: number }>(), { maxLength: 16000 })
const stage = ref('intraday')
const inputId = useId()
const models = { common, intraday: prompt, premarket, review, weekly }
const selected = computed(() => models[stage.value as keyof typeof models])
const text = computed({ get: () => selected.value.value, set: value => { selected.value.value = value } })
// 传入内置盘中提示词的配置（天才交易员）在盘中仍为内置时，盘前/日复盘留空改用本阶段内置提示词。
const intradayIsBuiltin = computed(() => props.defaultPrompt !== undefined && prompt.value.trim() === props.defaultPrompt.trim())
const blankStageSource = computed(() => intradayIsBuiltin.value ? '内置阶段提示词' : '盘中提示词')
const label = computed(() => ({ common: '共用基调', intraday: '盘中提示词', premarket: '盘前提示词', review: props.separateWeekly ? '日复盘提示词' : '盘后提示词', weekly: '周复盘提示词' })[stage.value])
</script>

<template>
  <div class="phase-prompt-editor space-y-3">
    <Tabs v-model="stage">
      <TabsList class="w-full" aria-label="提示词阶段">
        <TabsTrigger value="common" class="flex-1">共用基调</TabsTrigger>
        <TabsTrigger value="premarket" class="flex-1">盘前</TabsTrigger>
        <TabsTrigger value="intraday" class="flex-1">盘中</TabsTrigger>
        <TabsTrigger value="review" class="flex-1">{{ separateWeekly ? '日复盘' : '盘后' }}</TabsTrigger>
        <TabsTrigger v-if="separateWeekly" value="weekly" class="flex-1">周复盘</TabsTrigger>
      </TabsList>
    </Tabs>
    <div class="flex items-center justify-between gap-2">
      <Label :for="inputId">{{ label }}</Label>
      <span class="text-xs text-muted-foreground tabular-nums">{{ text.length }}{{ stage === 'weekly' ? ' 字符' : ` / ${maxLength}` }}</span>
    </div>
    <p class="text-xs text-muted-foreground leading-relaxed" aria-live="polite">
      <template v-if="stage === 'common'">各阶段共用的身份、风格与偏好，可留空。具体任务写在对应阶段，避免彼此冲突。</template>
      <template v-else-if="stage === 'weekly'">专用于整周总结、收益归因、仓位演变和下周方向。{{ text.trim() ? '使用本页内容与共用基调，不叠加日复盘或盘中提示词。' : '当前使用内置周复盘提示词与共用基调，不继承日复盘或盘中提示词。' }}</template>
      <template v-else-if="stage === 'intraday'">用于盘中、竞价和尾盘，与共用基调一起生效。{{ separateWeekly ? '盘前或日复盘留空时沿用自定义的这一份；周复盘使用独立配置。风格偏好请写入共用基调，才能到达全部阶段。' : '盘前或盘后未配置时回退到这一份。' }}</template>
      <template v-else>{{ stage === 'premarket' ? '用于盘前计划。' : separateWeekly ? '专用于日复盘，解释本日判断与下一交易日变化。' : '用于盘后研究。' }}{{ text.trim() ? '与共用基调一起生效，不叠加盘中提示词。' : `未独立配置，当前使用共用基调与${blankStageSource}。` }}</template>
    </p>
    <Textarea :id="inputId" v-model="text" :aria-label="label" :rows="12" :maxlength="stage === 'weekly' ? undefined : maxLength"
      class="h-64 min-h-40 max-h-[45vh] resize-y leading-relaxed [field-sizing:fixed]" :placeholder="stage === 'weekly' ? props.defaultWeeklyPrompt || '留空使用内置整周总结；不继承日复盘或盘中提示词' : stage === 'common' ? '各阶段共用的身份与偏好，无固定偏好可留空' : stage === 'intraday' ? '输入盘中任务与判断方法' : `留空时自动使用${blankStageSource}`" />
    <div class="flex justify-end">
      <Button v-if="stage === 'intraday' && props.defaultPrompt !== undefined" type="button" variant="ghost" size="sm" @click="prompt = props.defaultPrompt">恢复内置提示词</Button>
      <Button v-else-if="stage === 'weekly' && text" type="button" variant="ghost" size="sm" @click="text = ''">改用内置周复盘</Button>
      <Button v-else-if="stage === 'weekly' && props.defaultWeeklyPrompt" type="button" variant="ghost" size="sm" @click="text = props.defaultWeeklyPrompt">载入内置周复盘并编辑</Button>
      <Button v-else-if="(stage === 'premarket' || stage === 'review') && text" type="button" variant="ghost" size="sm" @click="text = ''">改用{{ blankStageSource }}</Button>
    </div>
  </div>
</template>
