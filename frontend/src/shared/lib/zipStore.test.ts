import { describe, expect, it } from 'vitest'

import { buildStoreZip, zipFolderFiles } from './zipStore'

describe('zipStore', () => {
  it('打出的 zip 带合法本地文件头', () => {
    const text = new TextEncoder().encode('---\nname: demo\ndescription: d\n---\nbody\n')
    const buf = buildStoreZip([{ path: 'demo/SKILL.md', data: text }])
    expect(buf[0]).toBe(0x50)
    expect(buf[1]).toBe(0x4b)
    expect(buf[2]).toBe(0x03)
    expect(buf[3]).toBe(0x04)
  })

  it('文件夹缺少 SKILL.md 时报错', async () => {
    const file = new File(['x'], 'readme.txt', { type: 'text/plain' })
    Object.defineProperty(file, 'webkitRelativePath', { value: 'pkg/readme.txt' })
    await expect(zipFolderFiles([file])).rejects.toThrow(/SKILL\.md/)
  })

  it('文件夹含 SKILL.md 时产出 zip File', async () => {
    const file = new File(
      ['---\nname: 测\ndescription: 说明\n---\n正文\n'],
      'SKILL.md',
      { type: 'text/markdown' },
    )
    Object.defineProperty(file, 'webkitRelativePath', { value: 'my-skill/SKILL.md' })
    const zip = await zipFolderFiles([file], 'my-skill.zip')
    expect(zip.name).toBe('my-skill.zip')
    expect(zip.size).toBeGreaterThan(30)
  })
})
