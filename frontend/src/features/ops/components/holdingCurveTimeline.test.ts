import { describe, expect, it } from 'vitest'
import type { HoldingCurvePoint } from '@/shared/types/holdingCurve'
import { buildCurveTimeline, drawdownAxisMin, inTradingSession } from './holdingCurveTimeline'
const point = (at:string,value:number|null,kind:HoldingCurvePoint['kind']='valuation'):HoldingCurvePoint => ({at,nav:value==null?null:1+value/100,pnl_cents:value==null?null:value*10000,drawdown_pct:value,quality:value==null?'unavailable':'verified',kind:value==null?'unavailable':kind})
const at = (s:string) => `2026-09-21T${s}:00+08:00`
describe('分时式展示坐标，不改动财务数据', () => {
  it('折叠隔夜、周末及休市空快照，无跨夜大空白', () => {
    const input=[point('2026-09-18T15:00:00+08:00',-1),point('2026-09-18T19:00:00+08:00',null),point('2026-09-19T10:00:00+08:00',null),point(at('09:30'),-.5)]
    const t=buildCurveTimeline(input,'drawdown')
    expect(t.mainData).toEqual([[0,-1],[1,-.5]])
    expect(t.bridges).toHaveLength(0);expect(t.days).toEqual([1]);expect(t.excluded).toBe(2)
  })
  it('真实盘中缺测以虚线连接端点，不填造中间数值', () => {
    const input=[point(at('10:00'),-.2),point(at('10:05'),null),point(at('10:10'),-.4)]
    const t=buildCurveTimeline(input,'drawdown')
    expect(t.mainData).toEqual([[0,-.2],[.5,null],[1,-.4]])
    expect(t.bridges).toEqual([{from:[0,-.2],to:[1,-.4]}])
    expect(t.samples.map(p=>p.index)).toEqual([0,2])
    expect(t.dataToSample).toEqual([0,null,1]);expect(t.sampleToData).toEqual([0,2])
    expect(input[1]!.nav).toBeNull()
  })
  it('午间休市不算缺测，午后继续曲线', () => {
    const t=buildCurveTimeline([point(at('11:30'),-.2),point(at('12:00'),null),point(at('13:00'),-.3)],'drawdown')
    expect(t.bridges).toHaveLength(0);expect(t.samples).toHaveLength(2)
  })
  it('盘中相隔较久但没有空快照，也显示未采样区段', () => {
    const t=buildCurveTimeline([point(at('10:00'),-.2),point(at('10:40'),-.3)],'drawdown')
    expect(t.bridges).toHaveLength(1)
  })
  it('末尾无效估值不外推到现在', () => {
    const t=buildCurveTimeline([point(at('15:00'),-1.07),point(at('18:00'),null)],'drawdown')
    expect(t.samples).toHaveLength(1);expect(t.samples[0]!.point.at).toBe(at('15:00'))
  })
  it('不同持仓轮次的基准点之间保持断开', () => {
    const t=buildCurveTimeline([point(at('10:00'),-1),point(at('10:05'),0,'baseline')],'drawdown')
    expect(t.bridges).toHaveLength(0);expect(t.mainData[1]).toEqual([.5,null])
  })
  it('当前样本范围决定纵轴，不被远处预警线压扁', () => {
    const t=buildCurveTimeline([point(at('10:00'),-1.65)],'drawdown')
    expect(drawdownAxisMin(t.samples,5)).toBe(-1.9)
    expect(drawdownAxisMin(buildCurveTimeline([point(at('10:00'),-4.8)],'drawdown').samples,5)).toBe(-5.6)
  })
  it('排序和切换指标不修改原点或遗漏真实低点', () => {
    const input=[point(at('10:10'),-.2),point(at('10:00'),-1.65),point('invalid',-9)]
    const before=JSON.stringify(input)
    for(const metric of ['drawdown','return','pnl'] as const) expect(buildCurveTimeline(input,metric).samples.map(p=>p.index)).toEqual([1,0])
    expect(JSON.stringify(input)).toBe(before)
  })
  it('全空数据和单样本不会生成虚假走势', () => {
    expect(buildCurveTimeline([point(at('10:00'),null)],'drawdown').mainData).toEqual([])
    expect(buildCurveTimeline([point(at('10:00'),0)],'drawdown').mainData).toEqual([[0,0]])
  })
  it.each([['09:29',false],['09:30',true],['11:30',true],['12:00',false],['13:00',true],['15:00',true],['15:01',false]])('休市边界 %s', (time,expected)=>expect(inTradingSession(Date.parse(at(String(time))))).toBe(expected))
})
