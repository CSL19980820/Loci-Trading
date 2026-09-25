import { describe, expect, it } from 'vitest'
import { guardianMessages } from './guardianConsultAdapter'
import type { GuardianConsultTurn } from '@/shared/types/guardian'
const base: GuardianConsultTurn = { id: 'turn', question: '实际情况', status: 'completed', created: 1000, result: { answer: '已核对' } }
describe('guardian consultation timeline adapter', () => {
  it('preserves legacy text and actual tool outcomes without inventing reasoning', () => {
    const messages = guardianMessages([{ ...base, result: { ...base.result, tools: [{name:'account',ok:false}] } }])
    expect(messages.map(row => row.id)).toEqual(['turn:user','turn:assistant'])
    expect(messages[1]).toMatchObject({content:'已核对',status:'done',tool_receipts:[{call_id:'turn:tool:0',name:'account',status:'error'}]})
    expect(messages[1]?.thinking).toBeUndefined()
    expect(messages[1]?.progress).toBeUndefined()
  })
  it('keeps native process evidence and failed partial answer', () => {
    const receipt = {call_id:'real-tool',name:'query',status:'error' as const,elapsed_ms:24}
    const answer = guardianMessages([{...base,status:'failed',result:{answer:'部分回答',thinking:'真实思考',phase:'error',tool_receipts:[receipt],error:'查询中断'}}])[1]
    expect(answer).toMatchObject({content:'部分回答',thinking:'真实思考',status:'error',progress:{phase:'error'},tool_receipts:[receipt],warnings:['查询中断']})
  })
  it('labels unknown old running progress honestly while keeping stable identity', () => {
    const running=guardianMessages([{...base,status:'running'}])[1]
    expect(running?.progress).toEqual({phase:'preparing',label:'正在研究（等待进度）'})
    expect(running?.id).toBe(guardianMessages([base])[1]?.id)
  })
})
