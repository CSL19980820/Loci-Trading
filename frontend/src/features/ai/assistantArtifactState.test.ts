import { describe, expect, it } from 'vitest'
import { artifactIdentity, normalizeArtifacts } from './assistantArtifactState'
import { applyAiRunEvent, beginAssistantTurn } from './assistantRunState'
import { parseEquityPayload, parseEchartsOption, parseKlineBars } from './assistantArtifacts'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'

const chart = (id:string, status:AiChartArtifact['status'], code='000980'):AiChartArtifact => ({id,kind:'qianlong_kline',title:`${code} 日 K`,status,data:{code,bars:[]}})
describe('artifact lifecycle', () => {
 it('replaces loading with the same stable ID and preserves metadata', () => {
  const result=normalizeArtifacts([chart('a','loading'),{...chart('a','ready'),data:{bars:[1]}}],true)
  expect(result).toHaveLength(1)
  expect(result[0]).toMatchObject({id:'a',status:'ready',data:{code:'000980',bars:[1]}})
 })
 it('reconciles a single unambiguous legacy placeholder', () => {
  expect(normalizeArtifacts([chart('old-loading','loading'),chart('new-ready','ready')])).toHaveLength(1)
 })
 it('does not merge different tickers or independent completed charts', () => {
  expect(normalizeArtifacts([chart('a','ready'),chart('b','ready')])).toHaveLength(2)
  expect(normalizeArtifacts([chart('a','loading'),chart('b','ready','600000')],true)).toHaveLength(2)
 })
 it('does not guess which concurrent legacy request completed', () => {
  expect(normalizeArtifacts([chart('a','loading'),chart('b','loading'),chart('c','ready')],true)).toHaveLength(3)
 })
 it('preserves completed chart identity during later prose updates', () => {
  const a=chart('a','ready')
  expect(normalizeArtifacts([a])[0]).toBe(a)
 })
 it('settles orphan placeholders without mutating historical input', () => {
  const a=chart('a','loading')
  expect(normalizeArtifacts([a])[0]).toMatchObject({status:'error'})
  expect(a.status).toBe('loading')
  expect(normalizeArtifacts([a],true)[0]?.status).toBe('loading')
 })
 it.each(['done','error','cancelled'])('settles outstanding artifacts on %s', type => {
  let state=beginAssistantTurn([],'fixture')
  state=applyAiRunEvent(state,{id:1,type:'artifact',data:{...chart('a','loading')}})
  state=applyAiRunEvent(state,{id:2,type,data:{}})
  expect(state.messages.at(-1)?.artifacts?.[0]?.status).toBe('error')
 })
 it('uses metadata or legacy title for code, never fabricates names', () => {
  expect(artifactIdentity({id:'x',kind:'kline',title:'000980 日 K',data:{}})).toEqual({code:'000980',name:''})
  expect(artifactIdentity({...chart('a','ready'),data:{stock_code:'600000',stock_name:'模拟名称'}})).toEqual({code:'600000',name:'模拟名称'})
 })
 it('reduces real loading/ready event IDs into one chart', () => {
  let state=beginAssistantTurn([],'fixture')
  state=applyAiRunEvent(state,{id:1,type:'artifact',data:{...chart('stable','loading')}})
  state=applyAiRunEvent(state,{id:2,type:'artifact',data:{...chart('stable','ready')}})
  expect(state.messages.at(-1)?.artifacts).toHaveLength(1)
  expect(state.messages.at(-1)?.artifacts?.[0]?.status).toBe('ready')
 })
})
describe('artifact data integrity', () => {
 it.each([null,undefined,'',Number.NaN,Infinity])('keeps date alignment and gaps for invalid value %s', missing => {
  expect(parseEquityPayload({dates:['d1','d2','d3'],values:[1,missing,3]})).toEqual({dates:['d1','d2','d3'],values:[1,null,3]})
 })
 it('retains missing dated points as gaps instead of connecting invented values', () => {
  expect(parseEquityPayload({points:[['d1',1],['d2',null],{date:'d3',nav:3}]})).toEqual({dates:['d1','d2','d3'],values:[1,null,3]})
 })
 it('does not shift subsequent values when an empty date is omitted', () => {
  expect(parseEquityPayload({dates:['d1','','d3'],values:[1,2,3]})).toEqual({dates:['d1','d3'],values:[1,3]})
 })
 it('accepts a single ECharts series and rejects unsupported types', () => {
  expect(parseEchartsOption({series:{type:'bar',data:[1]}})).not.toBeNull()
  expect(parseEchartsOption({series:{type:'custom',data:[1]}})).toBeNull()
  expect(parseEchartsOption({title:{text:'no data'}})).toBeNull()
 })
 it('parses valid OHLC and rejects null or non-finite prices', () => {
  expect(parseKlineBars({bars:[{date:'2026-01-01',open:'2',high:3,low:1,close:'2.5'},{open:null,high:3,low:1,close:2}]})).toEqual([{trade_date:'2026-01-01',open:2,high:3,low:1,close:2.5,volume:null,amount:null}])
 })
})
