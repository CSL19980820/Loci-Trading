// 构建产物体积统计（raw + gzip）。用法: bun scripts/dist-stats.mjs <distDir> [label]
import { readdirSync, statSync, readFileSync } from 'node:fs'
import { join, extname } from 'node:path'
import { gzipSync } from 'node:zlib'

const dir = process.argv[2] ?? 'dist'
const label = process.argv[3] ?? dir

function walk(root) {
  const out = []
  for (const name of readdirSync(root)) {
    const full = join(root, name)
    const st = statSync(full)
    if (st.isDirectory()) out.push(...walk(full))
    else out.push({ name, full, size: st.size })
  }
  return out
}

const files = walk(dir)
const kb = (n) => (n / 1024).toFixed(1).padStart(9)
const group = (ext) =>
  files
    .filter((f) => extname(f.name) === ext)
    .map((f) => ({ ...f, gz: gzipSync(readFileSync(f.full), { level: 9 }).length }))
    .sort((a, b) => b.size - a.size)

const js = group('.js')
const css = group('.css')
const total = files.reduce((a, f) => a + f.size, 0)
const sum = (arr, k) => arr.reduce((a, f) => a + f[k], 0)

console.log(`== ${label}`)
console.log(`dist total      : ${kb(total)} KB (${files.length} files)`)
console.log(`js  total     : ${kb(sum(js, 'size'))} KB raw / ${kb(sum(js, 'gz'))} KB gz (${js.length} chunks)`)
console.log(`css total     : ${kb(sum(css, 'size'))} KB raw / ${kb(sum(css, 'gz'))} KB gz (${css.length} files)`)

const html = readFileSync(join(dir, 'index.html'), 'utf8')
const entryNames = [...html.matchAll(/(?:src|href)="\/assets\/([^"]+)"/g)].map((m) => m[1])
const preload = [...html.matchAll(/modulepreload"[^>]*href="\/assets\/([^"]+)"/g)].map((m) => m[1])
const firstPaint = new Set([...entryNames, ...preload])
const fp = [...js, ...css].filter((f) => firstPaint.has(f.name))
console.log(
  `index.html 首屏: ${kb(sum(fp, 'size'))} KB raw / ${kb(sum(fp, 'gz'))} KB gz (${fp.length} files)`,
)
for (const f of fp.sort((a, b) => b.size - a.size)) {
  console.log(`   [first-paint] ${f.name.padEnd(40)}${kb(f.size)} KB  gz ${kb(f.gz)} KB`)
}
console.log('-- top 12 js chunks')
for (const f of js.slice(0, 12)) console.log(`   ${f.name.padEnd(44)}${kb(f.size)} KB  gz ${kb(f.gz)} KB`)
console.log('-- top 5 css')
for (const f of css.slice(0, 5)) console.log(` ${f.name.padEnd(44)}${kb(f.size)} KB  gz ${kb(f.gz)} KB`)
