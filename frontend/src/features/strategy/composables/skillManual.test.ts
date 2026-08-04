import { describe, expect, it } from 'vitest'

import { parseInline, parseSkillManual } from './skillManual'

describe('parseSkillManual', () => {
  it('按标题 / 段落 / 列表切块', () => {
    const blocks = parseSkillManual('# 用法\n\n先看这段。\n\n- 第一步\n- 第二步\n')
    expect(blocks).toEqual([
      { type: 'heading', level: 1, text: '用法' },
      { type: 'paragraph', text: '先看这段。' },
      { type: 'list', ordered: false, items: ['第一步', '第二步'] },
    ])
  })

  it('围栏代码原样保留，不再当 markdown 解析', () => {
    const blocks = parseSkillManual('```python\n# 这行是注释不是标题\nx = 1\n```')
    expect(blocks).toEqual([
      { type: 'code', lang: 'python', text: '# 这行是注释不是标题\nx = 1' },
    ])
  })

  it('有分隔行才认表格', () => {
    const blocks = parseSkillManual('| 字段 | 说明 |\n| --- | --- |\n| code | 代码 |')
    expect(blocks).toEqual([
      { type: 'table', rows: [['字段', '说明'], ['code', '代码']] },
    ])
  })

  it('普通句子里的竖线不会被误判成表格', () => {
    const blocks = parseSkillManual('用 a | b 表示或者。')
    expect(blocks).toEqual([{ type: 'paragraph', text: '用 a | b 表示或者。' }])
  })

  it('有序列表与引用各自成块', () => {
    const blocks = parseSkillManual('> 注意风险\n\n1. 先跑\n2. 再看\n')
    expect(blocks).toEqual([
      { type: 'quote', text: '注意风险' },
      { type: 'list', ordered: true, items: ['先跑', '再看'] },
    ])
  })

  it('空正文返回空数组', () => {
    expect(parseSkillManual('')).toEqual([])
  })
})

describe('parseInline', () => {
  it('解析加粗 / 行内代码 / 链接', () => {
    expect(
      parseInline('身份：**中国最激进**，见 `scripts/` 与 [文档](https://example.com)。'),
    ).toEqual([
      { type: 'text', text: '身份：' },
      { type: 'strong', text: '中国最激进' },
      { type: 'text', text: '，见 ' },
      { type: 'code', text: 'scripts/' },
      { type: 'text', text: ' 与 ' },
      { type: 'link', text: '文档', href: 'https://example.com' },
      { type: 'text', text: '。' },
    ])
  })

  it('斜体与纯文本', () => {
    expect(parseInline('用 *宁空勿弱* 收口')).toEqual([
      { type: 'text', text: '用 ' },
      { type: 'em', text: '宁空勿弱' },
      { type: 'text', text: ' 收口' },
    ])
    expect(parseInline('无标记')).toEqual([{ type: 'text', text: '无标记' }])
  })
})
