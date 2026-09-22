import { describe, expect, it } from 'vitest'
import { feedEpoch, feedPhase, guardianReportRows, guardianRunRows, latestAgentFeed } from './pulseAgentFeedModel'
import type { GuardianReviewSummary } from '@/shared/types/guardian'

const report = (period:GuardianReviewSummary['period'], time:string):GuardianReviewSummary => ({report_key:period,period,trade_date:time.slice(0,10),status:'success',created_at:time,summary:`${period}正文`})
describe('全阶段最新研判', () => {
  it('合并盘前盘中盘后周复盘后再排序，不按某个阶段过滤', () => {
    const rows=latestAgentFeed([...guardianReportRows([report('premarket','2026-09-21T08:30:00+08:00'),report('weekly','2026-09-18T20:00:00+08:00'),report('daily','2026-09-21T17:00:00+08:00')]),...guardianRunRows([{slot:'cycle',started:feedEpoch('2026-09-21T14:50:00+08:00')/1000,status:'success',result:{analysis:'盘中正文'}}])])
    expect(rows.map(r=>r.phaseLabel)).toEqual(['盘后复盘','盘中研判','盘前计划','周复盘'])
    expect(rows.map(r=>r.summary)).toEqual(['daily正文','盘中正文','premarket正文','weekly正文'])
  })
  it('一个来源的第5至16条仍可进入全局前16', () => {
    const runs=Array.from({length:20},(_,i)=>({slot:String(i),started:100000+i,status:'success',result:{analysis:String(i)}}))
    const rows=latestAgentFeed(guardianRunRows(runs))
    expect(rows).toHaveLength(16)
    expect(rows.map(r=>r.summary)).toEqual(Array.from({length:16},(_,i)=>String(19-i)))
  })
  it('星期五的周报能参与周一的排序，不限当天', () => {
    const rows=guardianReportRows([report('weekly','2026-09-18T20:00:00+08:00')])
    expect(latestAgentFeed(rows)).toHaveLength(1)
    expect(rows[0]!.phaseLabel).toBe('周复盘')
  })
  it('相同记录去重，但不同阶段不会因同日被覆盖', () => {
    const rows=guardianReportRows([report('premarket','2026-09-21T08:30:00+08:00'),report('daily','2026-09-21T17:00:00+08:00')])
    expect(latestAgentFeed([...rows,...rows])).toHaveLength(2)
  })
  it('未知时间排最后且不伪造为当前', () => {
    const rows=guardianReportRows([report('weekly','unknown'),report('daily','2026-09-21T17:00:00+08:00')])
    expect(latestAgentFeed(rows)[1]!.at).toBe('')
  })
  it('失败报告保留失败状态与原因', () => {
    const rows=guardianReportRows([{...report('daily','2026-09-21T17:00:00+08:00'),status:'failed',error:'测试错误'}])
    expect(rows[0]!.failed).toBe(true);expect(rows[0]!.summary).toBe('测试错误')
  })
  it.each(['2026-09-21 12:00:00','2026-09-21T12:00:00','2026-09-21T04:00:00Z'])('时区标准化 %s', text => expect(feedEpoch(text)).toBe(Date.parse('2026-09-21T12:00:00+08:00')))
  it('同时识别秒和毫秒时间戳并排除非法值', () => {
    const n=Date.parse('2026-09-21T12:00:00+08:00')
    expect(feedEpoch(n)).toBe(n);expect(feedEpoch(n/1000)).toBe(n)
    expect(feedEpoch(Infinity)).toBe(0);expect(feedEpoch('')).toBe(0)
  })
  it.each([['premarket','盘前计划'],['intraday','盘中研判'],['review','盘后复盘'],['weekly','周复盘']])('阶段标签 %s', (phase,label)=>expect(feedPhase(phase)).toBe(label))
})
