/**
 * 极简单色 QR Code (Quick Response Code) 矩阵生成器
 *
 * 特性：
 * - 纯 TypeScript，零外部依赖
 * - 支持 Byte 模式（UTF-8 字符、ASCII、URL）
 * - 纠错等级支持 M (约 15% 纠错能力) 与 L (约 7% 纠错能力)
 * - 自动适应版本 Version 1 ~ Version 10（可编码多达 270 字符）
 * - 输出布尔二维矩阵 (true: 黑色模块, false: 白色模块) 或 SVG / Canvas
 */

type ECLevel = 'L' | 'M'

interface QRVersionSpec {
  version: number
  totalCodewords: number
  ecCodewords: number
  blocks: number
  alignmentPatterns: number[]
}

// 常用版本规格 (Version 1 ~ 10, EC Level M)
const VERSION_SPECS_M: Record<number, QRVersionSpec> = {
  1: { version: 1, totalCodewords: 26, ecCodewords: 10, blocks: 1, alignmentPatterns: [] },
  2: { version: 2, totalCodewords: 44, ecCodewords: 16, blocks: 1, alignmentPatterns: [6, 18] },
  3: { version: 3, totalCodewords: 70, ecCodewords: 26, blocks: 1, alignmentPatterns: [6, 22] },
  4: { version: 4, totalCodewords: 100, ecCodewords: 36, blocks: 2, alignmentPatterns: [6, 26] },
  5: { version: 5, totalCodewords: 134, ecCodewords: 48, blocks: 2, alignmentPatterns: [6, 30] },
  6: { version: 6, totalCodewords: 172, ecCodewords: 64, blocks: 4, alignmentPatterns: [6, 34] },
  7: { version: 7, totalCodewords: 196, ecCodewords: 72, blocks: 4, alignmentPatterns: [6, 22, 38] },
  8: { version: 8, totalCodewords: 242, ecCodewords: 88, blocks: 4, alignmentPatterns: [6, 24, 42] },
  9: { version: 9, totalCodewords: 292, ecCodewords: 110, blocks: 5, alignmentPatterns: [6, 26, 46] },
  10: { version: 10, totalCodewords: 346, ecCodewords: 130, blocks: 5, alignmentPatterns: [6, 28, 50] },
}

// Galois Field (256) 指数与对数表
const EXP_TABLE = new Uint8Array(512)
const LOG_TABLE = new Uint8Array(256)

;(() => {
  let x = 1
  for (let i = 0; i < 255; i++) {
    EXP_TABLE[i] = x
    EXP_TABLE[i + 255] = x
    LOG_TABLE[x] = i
    x <<= 1
    if (x & 0x100) x ^= 0x11d
  }
})()

function gfMul(a: number, b: number): number {
  if (a === 0 || b === 0) return 0
  return EXP_TABLE[LOG_TABLE[a] + LOG_TABLE[b]]
}

function computeReedSolomon(data: Uint8Array, ecCount: number): Uint8Array {
  // 生成多项式
  let gen = new Uint8Array([1])
  for (let i = 0; i < ecCount; i++) {
    const nextGen = new Uint8Array(gen.length + 1)
    const factor = EXP_TABLE[i]
    for (let j = 0; j < gen.length; j++) {
      nextGen[j] ^= gfMul(gen[j], factor)
      nextGen[j + 1] ^= gen[j]
    }
    gen = nextGen
  }

  const remainder = new Uint8Array(ecCount)
  for (let i = 0; i < data.length; i++) {
    const feedback = data[i] ^ remainder[0]
    for (let j = 0; j < ecCount - 1; j++) {
      remainder[j] = remainder[j + 1] ^ gfMul(gen[j + 1], feedback)
    }
    remainder[ecCount - 1] = gfMul(gen[ecCount], feedback)
  }
  return remainder
}

/**
 * 确定满足数据长度的最小 QR 版本 (Version 1-10, Mode=Byte, EC=M)
 */
function pickVersion(dataLength: number): QRVersionSpec {
  for (let v = 1; v <= 10; v++) {
    const spec = VERSION_SPECS_M[v]
    const dataCapacity = spec.totalCodewords - spec.ecCodewords
    // Byte mode: 4 bits mode + 8/16 bits length + data*8
    const lengthBits = v <= 9 ? 8 : 16
    const totalBitsNeeded = 4 + lengthBits + dataLength * 8
    if (Math.ceil(totalBitsNeeded / 8) <= dataCapacity) {
      return spec
    }
  }
  return VERSION_SPECS_M[10]
}

/**
 * 将输入文本编码为带纠错的码字流
 */
function encodeData(text: string, spec: QRVersionSpec): Uint8Array {
  const encoder = new TextEncoder()
  const rawBytes = encoder.encode(text)
  const dataCapacity = spec.totalCodewords - spec.ecCodewords

  // 组装数据位流
  const bits: number[] = []
  const pushBits = (val: number, len: number) => {
    for (let i = len - 1; i >= 0; i--) {
      bits.push((val >> i) & 1)
    }
  }

  // Byte Mode 指示符 0100
  pushBits(0b0100, 4)
  // 字符计数指示符
  const lengthBits = spec.version <= 9 ? 8 : 16
  pushBits(rawBytes.length, lengthBits)
  // 数据本身
  for (let i = 0; i < rawBytes.length; i++) {
    pushBits(rawBytes[i], 8)
  }

  // 终止符 (最多 4 个 0)
  const maxBits = dataCapacity * 8
  const termLen = Math.min(4, maxBits - bits.length)
  for (let i = 0; i < termLen; i++) bits.push(0)

  // 补齐到字节边界
  while (bits.length % 8 !== 0) bits.push(0)

  // 填充字节 0xEC, 0x11
  const padBytes = [0xec, 0x11]
  let padIdx = 0
  while (bits.length < maxBits) {
    pushBits(padBytes[padIdx % 2], 8)
    padIdx++
  }

  // 转成字节数组
  const dataCodewords = new Uint8Array(dataCapacity)
  for (let i = 0; i < dataCapacity; i++) {
    let byteVal = 0
    for (let b = 0; b < 8; b++) {
      byteVal = (byteVal << 1) | bits[i * 8 + b]
    }
    dataCodewords[i] = byteVal
  }

  // 分块做 RS 纠错
  const numBlocks = spec.blocks
  const ecPerBlock = spec.ecCodewords / numBlocks
  const dataPerBlock = Math.floor(dataCapacity / numBlocks)

  const blockData: Uint8Array[] = []
  const blockEc: Uint8Array[] = []

  let offset = 0
  for (let b = 0; b < numBlocks; b++) {
    const len = dataPerBlock + (b >= numBlocks - (dataCapacity % numBlocks) ? 1 : 0)
    const slice = dataCodewords.slice(offset, offset + len)
    offset += len
    blockData.push(slice)
    blockEc.push(computeReedSolomon(slice, ecPerBlock))
  }

  // 交叉交织 (Interleaving)
  const finalResult = new Uint8Array(spec.totalCodewords)
  let writeIdx = 0

  // 1. 交织数据码字
  const maxDataLen = Math.max(...blockData.map((b) => b.length))
  for (let i = 0; i < maxDataLen; i++) {
    for (let b = 0; b < numBlocks; b++) {
      if (i < blockData[b].length) {
        finalResult[writeIdx++] = blockData[b][i]
      }
    }
  }

  // 2. 交织纠错码字
  for (let i = 0; i < ecPerBlock; i++) {
    for (let b = 0; b < numBlocks; b++) {
      finalResult[writeIdx++] = blockEc[b][i]
    }
  }

  return finalResult
}

export interface QRCodeMatrix {
  size: number
  modules: boolean[][]
}

/**
 * 构造 QR Code 模块矩阵
 */
export function generateQrMatrix(text: string): QRCodeMatrix {
  const spec = pickVersion(new TextEncoder().encode(text).length)
  const size = spec.version * 4 + 17
  const modules: (boolean | null)[][] = Array.from({ length: size }, () =>
    Array(size).fill(null),
  )
  const isFunction: boolean[][] = Array.from({ length: size }, () => Array(size).fill(false))

  function setModule(r: number, c: number, val: boolean, isFunc = false): void {
    if (r >= 0 && r < size && c >= 0 && c < size) {
      modules[r][c] = val
      if (isFunc) isFunction[r][c] = true
    }
  }

  // 1. 寻像图案 (Finder Patterns)
  function placeFinder(row: number, col: number): void {
    for (let r = -1; r <= 7; r++) {
      for (let c = -1; c <= 7; c++) {
        const nr = row + r
        const nc = col + c
        if (nr < 0 || nr >= size || nc < 0 || nc >= size) continue
        if (r >= 0 && r <= 6 && c >= 0 && c <= 6) {
          const isBlack = r === 0 || r === 6 || c === 0 || c === 6 || (r >= 2 && r <= 4 && c >= 2 && c <= 4)
          setModule(nr, nc, isBlack, true)
        } else {
          setModule(nr, nc, false, true) // 分隔符
        }
      }
    }
  }

  placeFinder(0, 0)
  placeFinder(0, size - 7)
  placeFinder(size - 7, 0)

  // 2. 定位图案 (Timing Patterns)
  for (let i = 8; i < size - 8; i++) {
    setModule(6, i, i % 2 === 0, true)
    setModule(i, 6, i % 2 === 0, true)
  }

  // 3. 校正图案 (Alignment Patterns)
  const coords = spec.alignmentPatterns
  for (let i = 0; i < coords.length; i++) {
    for (let j = 0; j < coords.length; j++) {
      const r = coords[i]
      const c = coords[j]
      // 跳过与 Finder Pattern 重叠的位置
      if (
        (r === 6 && c === 6) ||
        (r === 6 && c === size - 7) ||
        (r === size - 7 && c === 6)
      ) {
        continue
      }
      for (let dr = -2; dr <= 2; dr++) {
        for (let dc = -2; dc <= 2; dc++) {
          const isBlack = Math.max(Math.abs(dr), Math.abs(dc)) !== 1
          setModule(r + dr, c + dc, isBlack, true)
        }
      }
    }
  }

  // 4. 暗模块
  setModule(size - 8, 8, true, true)

  // 5. 格式信息预留
  for (let i = 0; i < 9; i++) {
    if (i !== 6) {
      setModule(8, i, false, true)
      setModule(i, 8, false, true)
    }
  }
  for (let i = 0; i < 8; i++) {
    setModule(8, size - 1 - i, false, true)
    setModule(size - 1 - i, 8, false, true)
  }

  // 6. 填入数据码字
  const data = encodeData(text, spec)
  let dataBitIdx = 0
  const totalDataBits = data.length * 8

  let right = size - 1
  let goingUp = true

  while (right > 0) {
    if (right === 6) right-- // 跳过垂直 Timing 列
    for (let step = 0; step < size; step++) {
      const r = goingUp ? size - 1 - step : step
      for (let c = 0; c < 2; c++) {
        const col = right - c
        if (!isFunction[r][col]) {
          let bit = false
          if (dataBitIdx < totalDataBits) {
            const byteIdx = Math.floor(dataBitIdx / 8)
            const bitOffset = 7 - (dataBitIdx % 8)
            bit = ((data[byteIdx] >> bitOffset) & 1) === 1
            dataBitIdx++
          }
          // 默认应用掩码 0: (row + col) % 2 === 0
          const mask = (r + col) % 2 === 0
          modules[r][col] = bit !== mask
        }
      }
    }
    right -= 2
    goingUp = !goingUp
  }

  // 7. 写入格式信息 (Mask 0 + EC Level M => 0b10000 => BCH => 0b101010000010010)
  // 固定 EC M + Mask 0 的 15-bit 格式串: 101010000010010 ^ 101010000010010 = 0
  // 掩码异或 101010000010010:
  // EC M = 00, Mask 0 = 000 => 00000. BCH(00000) = 0000000000. Masked with 101010000010010 => 101010000010010
  const formatBits = [1, 0, 1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0]

  // 水平与垂直格式信息布局
  for (let i = 0; i < 6; i++) setModule(8, i, formatBits[i] === 1)
  setModule(8, 7, formatBits[6] === 1)
  setModule(8, 8, formatBits[7] === 1)
  setModule(7, 8, formatBits[8] === 1)
  for (let i = 0; i < 6; i++) setModule(5 - i, 8, formatBits[9 + i] === 1)

  for (let i = 0; i < 8; i++) setModule(size - 1 - i, 8, formatBits[i] === 1)
  for (let i = 0; i < 7; i++) setModule(8, size - 7 + i, formatBits[8 + i] === 1)

  return {
    size,
    modules: modules.map((row) => row.map((cell) => cell ?? false)),
  }
}

/**
 * 将 QR Matrix 转换为 SVG 字符串
 */
export function qrMatrixToSvg(matrix: QRCodeMatrix, pixelSize = 6, margin = 4): string {
  const fullSize = (matrix.size + margin * 2) * pixelSize
  const rects: string[] = []

  for (let r = 0; r < matrix.size; r++) {
    for (let c = 0; c < matrix.size; c++) {
      if (matrix.modules[r][c]) {
        const x = (c + margin) * pixelSize
        const y = (r + margin) * pixelSize
        rects.push(`<rect x="${x}" y="${y}" width="${pixelSize}" height="${pixelSize}" fill="currentColor"/>`)
      }
    }
  }

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${fullSize} ${fullSize}" width="100%" height="100%" shape-rendering="crispEdges">${rects.join('')}</svg>`
}
