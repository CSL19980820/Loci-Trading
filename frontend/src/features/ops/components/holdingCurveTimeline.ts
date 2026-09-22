import type { HoldingCurvePoint } from '@/shared/types/holdingCurve'
import { curvePointValue, curveTimestamp, type CurveMetric } from './holdingCurvePresentation'

export interface CurveSample {
  point: HoldingCurvePoint
  index: number
  timestamp: number
  value: number
  gapBefore: boolean
  restart: boolean
}
/** Only used to distinguish a missing observation from a closed-market timestamp. */
export function inTradingSession(timestamp: number): boolean {
  const d = new Date(timestamp + 8 * 3600000)
  const minute = d.getUTCHours() * 60 + d.getUTCMinutes()
  return d.getUTCDay() !== 0 && d.getUTCDay() !== 6 && ((minute >= 570 && minute <= 690) || (minute >= 780 && minute <= 900))
}
export function curveSessionDay(timestamp:number):string {
  return new Date(timestamp + 8 * 3600000).toISOString().slice(0,10)
}

/** A display-only, compressed sample axis. Never forward-fill or calculate missing NAVs. */
export function buildCurveTimeline(points:HoldingCurvePoint[], metric:CurveMetric, range?: {start:string;end:string}) {
  const sorted = points.map((point,index) => ({point,index,timestamp:curveTimestamp(point.at)}))
    .filter(p => Number.isFinite(p.timestamp) && (!range || (curveSessionDay(p.timestamp) >= range.start.slice(0,10) && curveSessionDay(p.timestamp) <= range.end.slice(0,10))))
    .sort((a,b) => a.timestamp-b.timestamp || a.index-b.index)
  const samples:CurveSample[] = []
  let missing = false, excluded = 0
  for (const p of sorted) {
    const value = curvePointValue(p.point, metric)
    if (value == null) {
      excluded++
      if (inTradingSession(p.timestamp)) missing = true
      continue
    }
    const prev = samples.at(-1)
    const sameDay = prev && curveSessionDay(prev.timestamp) === curveSessionDay(p.timestamp)
    // Widely spaced observations during one session are not a verified continuous trace.
    const sameSession = prev && (new Date(prev.timestamp+8*3600000).getUTCHours()<12) === (new Date(p.timestamp+8*3600000).getUTCHours()<12)
    const gap = Boolean(prev && (missing || (sameDay && sameSession && p.timestamp-prev.timestamp>20*60000)))
    samples.push({...p,value,gapBefore:gap,restart:Boolean(prev && p.point.kind==='baseline')})
    missing = false
  }
  const mainData: [number, number | null][] = []
  const dataToSample: (number | null)[] = []
  const sampleToData: number[] = []
  const bridges: { from:[number,number]; to:[number,number] }[] = []
  const days: number[] = []
  samples.forEach((s,i) => {
    if (i && (s.gapBefore || s.restart)) {
      mainData.push([i-.5,null]); dataToSample.push(null)
      if (!s.restart) bridges.push({from:[i-1,samples[i-1]!.value],to:[i,s.value]})
    }
    if (i && curveSessionDay(s.timestamp)!==curveSessionDay(samples[i-1]!.timestamp)) days.push(i)
    sampleToData.push(mainData.length); mainData.push([i,s.value]); dataToSample.push(i)
  })
  return {samples,mainData,dataToSample,sampleToData,bridges,days,excluded}
}

export function drawdownAxisMin(samples:CurveSample[], threshold:number):number {
  const deepest = Math.max(.2,...samples.map(s => Math.abs(s.value)))
  const extent = deepest >= threshold*.75 ? Math.max(threshold,deepest) : deepest
  return -Math.ceil(extent*1.12*10 - 1e-9)/10
}
