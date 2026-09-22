import { describe, expect, it } from 'vitest'
import type { HoldingCurvePoint } from '@/shared/types/holdingCurve'
import { buildCurveTimeline } from './holdingCurveTimeline'
import { curveRangeStatistics } from './holdingCurveStatistics'
import type { CurveMetric } from './holdingCurvePresentation'

const point = (hour:string, nav:number|null, dd:number|null, pnl:number|null, patch:Partial<HoldingCurvePoint>={}):HoldingCurvePoint => ({
  at:`2026-09-21T${hour}:00+08:00`, nav, drawdown_pct:dd, pnl_cents:pnl,
  kind:nav==null?'unavailable':'valuation', quality:nav==null?'unavailable':'verified', ...patch,
})
const stats = (points:HoldingCurvePoint[], mode:CurveMetric='drawdown') => curveRangeStatistics(buildCurveTimeline(points,mode).samples)

describe('所选区间的采样均值、极值与净值低高幅度', () => {
  it('均值等权取真实采样，不将缺口当作零或虚构中间点', () => {
    const values=[point('10:00',1,0,0),point('10:05',null,null,null),point('10:10',.98,-2,-20000),point('10:15',.99,-1,-10000)]
    const result=stats(values)!
    expect(result.count).toBe(3);expect(result.average).toBe(-1)
    expect(result.minimum.index).toBe(2);expect(result.maximum.index).toBe(0)
    expect(result.spread).toBe(2);expect(result.navRangePct).toBeCloseTo((1/.98-1)*100)
  })
  it('收益率跨零时用单位净值计算低高涨幅，不除以负收益率', () => {
    const result=stats([point('10:00',.9,-10,-10000),point('11:00',1.1,0,10000)],'return')!
    expect(result.average).toBeCloseTo(0)
    expect(result.spread).toBeCloseTo(20)
    expect(result.navRangePct).toBeCloseTo(22.22222222)
  })
  it('金额视图高低差额以元显示，百分比仍基于净值', () => {
    const result=stats([point('10:00',.9,-10,-100000),point('11:00',1.1,0,100000)],'pnl')!
    expect(result.minimum.value).toBe(-1000);expect(result.maximum.value).toBe(1000)
    expect(result.spread).toBe(2000);expect(result.average).toBe(0)
    expect(result.navRangePct).toBeCloseTo(22.22222222)
  })
  it('峰值先出现也保留真正区间极值与时点，不伪称为后续反弹', () => {
    const result=stats([point('10:00',1.1,0,10000),point('11:00',.9,-18.18,-10000)],'return')!
    expect(result.navMaximum!.timestamp).toBeLessThan(result.navMinimum!.timestamp)
    expect(result.navRangePct).toBeCloseTo(22.22222222)
  })
  it('净值为零，不输出Infinity或虚假涨幅', () => {
    const result=stats([point('10:00',0,-100,-100000),point('11:00',1,0,0)])!
    expect(result.navRangePct).toBeNull();expect(result.navRangeUnavailable).toBe('zero-base')
    expect(result.minimum.value).toBe(-100)
  })
  it('单点只有极值和均值，不编造区间涨幅', () => {
    const result=stats([point('10:00',1.1,0,100)])!
    expect(result.minimum).toBe(result.maximum);expect(result.average).toBe(0)
    expect(result.navRangePct).toBeNull();expect(result.navRangeUnavailable).toBe('single-sample')
  })
  it('同值多点使用一个确定极值时点，涨幅为零', () => {
    const result=stats([point('10:00',1,0,0),point('10:10',1,0,0)])!
    expect(result.minimum.index).toBe(0);expect(result.maximum.index).toBe(0)
    expect(result.average).toBe(0);expect(result.spread).toBe(0);expect(result.navRangePct).toBe(0)
  })
  it('重新开仓不跨不同基准计算百分比涨幅', () => {
    const result=stats([point('10:00',1.1,0,100),point('11:00',1,0,0,{kind:'baseline'})],'return')!
    expect(result.navRangePct).toBeNull();expect(result.navRangeUnavailable).toBe('different-episodes')
  })
  it.each(['drawdown','return','pnl'] as const)('%s 指标只在有效点上求极值，不改变源数据', metric => {
    const input=[point('11:00',1.01,-.5,500),point('10:00',.99,-1.5,-500),point('12:00',null,null,null)]
    const before=JSON.stringify(input),result=stats(input,metric)!
    expect(result.count).toBe(2);expect(result.minimum.index).toBe(1)
    expect(result.maximum.index).toBe(0);expect(JSON.stringify(input)).toBe(before)
  })
  it.each([NaN,Infinity,-Infinity,-1])('非法净值 %s 不参与平均或极值', nav => {
    expect(stats([point('10:00',nav,-99,999999),point('11:00',1,0,0)])!.count).toBe(1)
  })
  it('全部缺测返回空，而不是0收益', () => {
    expect(stats([point('10:00',null,null,null)])).toBeNull()
    expect(stats([])).toBeNull()
  })
  it('北京时间范围筛选含端点且保留原始点索引', () => {
    const input=[point('10:00',10,0,9000,{at:'2026-09-19T10:00:00+08:00'}),
      point('10:00',1.2,0,200,{at:'2026-09-19T16:00:00Z'}),
      point('11:00',.8,-33.3,-200,{at:'2026-09-21T15:59:59Z'}),
      point('12:00',.1,-90,-900,{at:'2026-09-21T16:00:00Z'})]
    const timeline=buildCurveTimeline(input,'return',{start:'2026-09-20',end:'2026-09-21'})
    const result=curveRangeStatistics(timeline.samples)!
    expect(timeline.samples.map(s=>s.index)).toEqual([1,2]);expect(result.count).toBe(2)
    expect(result.navRangePct).toBeCloseTo(50)
    expect(curveRangeStatistics(buildCurveTimeline(input,'return',{start:'2026-09-22',end:'2026-09-22'}).samples)!.count).toBe(1)
  })
  it('金额缺失只影响该视图，不把缺失金额替成零', () => {
    const input=[point('10:00',.9,-10,null),point('11:00',1,0,0)]
    expect(stats(input,'pnl')!.count).toBe(1);expect(stats(input,'return')!.count).toBe(2)
  })
  it('不因极端但有限的数值溢出均值累计', () => {
    const samples=buildCurveTimeline([point('10:00',1,0,0),point('11:00',1,0,0)],'pnl').samples
    samples.forEach(sample=>sample.value=1e308)
    expect(curveRangeStatistics(samples)!.average).toBe(1e308)
  })
})
