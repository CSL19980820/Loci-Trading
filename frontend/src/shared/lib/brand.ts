/** 产品品牌。潜龙是其中一个战法，不是系统名。 */
export const BRAND_NAME = 'Loci'
export const BRAND_MARK = 'LC'
export const BRAND_TAGLINE = '多战法账本'

export function brandTitle(page?: string): string {
  return page ? `${page}｜${BRAND_NAME}` : BRAND_NAME
}
