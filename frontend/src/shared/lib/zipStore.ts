/** 浏览器端 STORE 压缩 zip（不依赖第三方）。用于把文件夹选中的 File 打成技能包。 */

const CRC_TABLE = (() => {
  const table = new Uint32Array(256)
  for (let i = 0; i < 256; i += 1) {
    let c = i
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    table[i] = c >>> 0
  }
  return table
})()

function crc32(data: Uint8Array): number {
  let c = 0xffffffff
  for (let i = 0; i < data.length; i += 1) c = CRC_TABLE[(c ^ data[i]!) & 0xff]! ^ (c >>> 8)
  return (c ^ 0xffffffff) >>> 0
}

function u16(n: number): Uint8Array {
  const out = new Uint8Array(2)
  out[0] = n & 0xff
  out[1] = (n >>> 8) & 0xff
  return out
}

function u32(n: number): Uint8Array {
  const out = new Uint8Array(4)
  out[0] = n & 0xff
  out[1] = (n >>> 8) & 0xff
  out[2] = (n >>> 16) & 0xff
  out[3] = (n >>> 24) & 0xff
  return out
}

function concat(chunks: Uint8Array[]): Uint8Array {
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0)
  const out = new Uint8Array(total)
  let offset = 0
  for (const chunk of chunks) {
    out.set(chunk, offset)
    offset += chunk.length
  }
  return out
}

export type ZipEntry = { path: string; data: Uint8Array }

/** 生成未压缩 zip；path 用 `/`，勿以 `/` 开头。 */
export function buildStoreZip(entries: ZipEntry[]): Uint8Array {
  const locals: Uint8Array[] = []
  const centrals: Uint8Array[] = []
  let offset = 0

  for (const entry of entries) {
    const nameBytes = new TextEncoder().encode(entry.path.replace(/\\/g, '/'))
    const crc = crc32(entry.data)
    const size = entry.data.length
    const local = concat([
      u32(0x04034b50),
      u16(20),
      u16(0),
      u16(0),
      u16(0),
      u16(0),
      u32(crc),
      u32(size),
      u32(size),
      u16(nameBytes.length),
      u16(0),
      nameBytes,
      entry.data,
    ])
    const central = concat([
      u32(0x02014b50),
      u16(20),
      u16(20),
      u16(0),
      u16(0),
      u16(0),
      u16(0),
      u32(crc),
      u32(size),
      u32(size),
      u16(nameBytes.length),
      u16(0),
      u16(0),
      u16(0),
      u16(0),
      u32(0),
      u32(offset),
      nameBytes,
    ])
    locals.push(local)
    centrals.push(central)
    offset += local.length
  }

  const centralBlob = concat(centrals)
  const end = concat([
    u32(0x06054b50),
    u16(0),
    u16(0),
    u16(entries.length),
    u16(entries.length),
    u32(centralBlob.length),
    u32(offset),
    u16(0),
  ])
  return concat([...locals, centralBlob, end])
}

/** 把 `<input webkitdirectory>` 选中的文件打成 zip File。 */
export async function zipFolderFiles(files: FileList | File[], zipName = 'skill.zip'): Promise<File> {
  const list = Array.from(files).filter((file) => file.size > 0 || file.name)
  if (!list.length) throw new Error('文件夹是空的')
  const entries: ZipEntry[] = []
  for (const file of list) {
    const path = (file.webkitRelativePath || file.name).replace(/\\/g, '/')
    if (!path || path.endsWith('/')) continue
    entries.push({ path, data: new Uint8Array(await file.arrayBuffer()) })
  }
  if (!entries.length) throw new Error('文件夹里没有可上传的文件')
  const hasManifest = entries.some((e) => /(^|\/)SKILL\.md$/i.test(e.path))
  if (!hasManifest) throw new Error('文件夹里找不到 SKILL.md')
  const bytes = buildStoreZip(entries)
  return new File([new Uint8Array(bytes)], zipName, { type: 'application/zip' })
}
