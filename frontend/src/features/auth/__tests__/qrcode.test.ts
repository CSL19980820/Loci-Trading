import { describe, expect, it } from 'vitest'
import { generateQrMatrix, qrMatrixToSvg } from '@/shared/lib/qrcode'

describe('QR Code generator (qrcode.ts)', () => {
  it('generates a valid QR matrix for plain text', () => {
    const text = 'https://example.com/loci-auth?state=abc12345'
    const matrix = generateQrMatrix(text)

    expect(matrix.size).toBeGreaterThanOrEqual(21)
    expect(matrix.modules.length).toBe(matrix.size)
    expect(matrix.modules[0].length).toBe(matrix.size)

    // Finder patterns must be present at corners
    // Top-left finder center (row 3, col 3) is true
    expect(matrix.modules[3][3]).toBe(true)
    // Top-left finder border (row 0, col 0) is true
    expect(matrix.modules[0][0]).toBe(true)
  })

  it('generates svg output string', () => {
    const matrix = generateQrMatrix('test-qr')
    const svg = qrMatrixToSvg(matrix, 4, 2)

    expect(svg).toContain('<svg')
    expect(svg).toContain('</svg>')
    expect(svg).toContain('<rect')
  })
})
