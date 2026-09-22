import type { CurveSample } from './holdingCurveTimeline'

export interface CurveRangeStatistics {
  count: number
  minimum: CurveSample
  maximum: CurveSample
  latest: CurveSample
  average: number
  spread: number
  navMinimum: CurveSample | null
  navMaximum: CurveSample | null
  navRangePct: number | null
  navRangeUnavailable: 'single-sample' | 'zero-base' | 'different-episodes' | null
}

/** Equal-weight mean of real, displayed samples. Missing intervals never add synthetic observations. */
export function curveRangeStatistics(samples: readonly CurveSample[]): CurveRangeStatistics | null {
  const valid = samples.filter(sample => sample.point.quality === 'verified'
    && Number.isFinite(sample.timestamp) && Number.isFinite(sample.value)
    && sample.point.nav != null && Number.isFinite(sample.point.nav))
  if (!valid.length) return null
  let minimum = valid[0]!, maximum = valid[0]!, latest = valid[0]!
  let navMinimum: CurveSample | null = null, navMaximum: CurveSample | null = null
  // Sum divided terms to avoid overflowing the accumulator with large monetary values.
  let average = 0, correction = 0
  for (const sample of valid) {
    if (sample.value < minimum.value) minimum = sample
    if (sample.value > maximum.value) maximum = sample
    if (sample.timestamp >= latest.timestamp) latest = sample
    const term = sample.value / valid.length - correction
    const sum = average + term
    correction = (sum - average) - term
    average = sum
    if (sample.point.nav! >= 0) {
      if (!navMinimum || sample.point.nav! < navMinimum.point.nav!) navMinimum = sample
      if (!navMaximum || sample.point.nav! > navMaximum.point.nav!) navMaximum = sample
    }
  }
  let navRangeUnavailable: CurveRangeStatistics['navRangeUnavailable'] = null
  if (valid.length < 2) navRangeUnavailable = 'single-sample'
  else if (valid.some((sample, index) => index > 0 && sample.restart)) navRangeUnavailable = 'different-episodes'
  else if (!navMinimum || !navMaximum || navMinimum.point.nav! <= 0) navRangeUnavailable = 'zero-base'
  const relative = navRangeUnavailable ? null : (navMaximum!.point.nav! / navMinimum!.point.nav! - 1) * 100
  return {
    count: valid.length, minimum, maximum, latest, average, spread: maximum.value - minimum.value,
    navMinimum, navMaximum, navRangePct: relative != null && Number.isFinite(relative) ? relative : null,
    navRangeUnavailable,
  }
}
