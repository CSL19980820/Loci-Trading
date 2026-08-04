import { describe, expect, it } from 'vitest'

import { formatSkillRunEvent } from './skillRunLog'

describe('formatSkillRunEvent', () => {
  it('translates phases and stop reasons to Chinese', () => {
    expect(formatSkillRunEvent({ type: 'phase', name: 'subagents' })).toBe(
      '▸ 进入阶段 · 并行弹药子任务',
    )
    expect(formatSkillRunEvent({ type: 'phase', name: 'main_agent' })).toBe(
      '▸ 进入阶段 · 主脑推理',
    )
    expect(formatSkillRunEvent({ type: 'done', stopped_reason: 'completed' })).toBe(
      '■ 正常完成',
    )
    expect(formatSkillRunEvent({ type: 'done', stopped_reason: 'max_rounds' })).toBe(
      '■ 达到轮数上限',
    )
  })

  it('renders detailed subagent and tool lifecycle lines', () => {
    expect(
      formatSkillRunEvent({ type: 'subagent_start', id: 'scan', kind: 'cli' }),
    ).toBe('▷ 子任务启动 · scan（命令行）')
    expect(
      formatSkillRunEvent({
        type: 'subagent_end',
        id: 'scan',
        ok: true,
        preview: '扫到 3 只候选',
      }),
    ).toBe('✓ 子任务完成 · scan · 扫到 3 只候选')
    expect(
      formatSkillRunEvent({
        type: 'tool_start',
        name: 'ask_user',
        arguments: { prompt: '选 A 还是 B？' },
      }),
    ).toBe('→ 调用 · 向你提问（选 A 还是 B？）')
    expect(
      formatSkillRunEvent({
        type: 'tool_end',
        name: 'write_journal',
        ok: true,
        preview: '已写入 journal/note.md',
      }),
    ).toBe('✓ 完成 · 写入技能日志 · 已写入 journal/note.md')
  })

  it('covers rounds, waiting, and errors', () => {
    expect(formatSkillRunEvent({ type: 'round_start', round: 2 })).toBe('◉ 第 2 轮思考')
    expect(
      formatSkillRunEvent({
        type: 'waiting_user',
        ask: { prompt: '要不要继续扫板？' },
      }),
    ).toBe('⏸ 等待你的回复 · 要不要继续扫板？')
    expect(formatSkillRunEvent({ type: 'error', message: '超时' })).toBe('✗ 错误 · 超时')
    expect(formatSkillRunEvent({ type: 'unknown' })).toBeNull()
  })
})
