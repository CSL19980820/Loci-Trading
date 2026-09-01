/**
 * 把压缩栈里的 `chunk.js:行:列` 还原成源码位置。
 * 用法：node e2e/_resolve.cjs QuantView-gM3EQLkO.js 11 270 [10 39817 ...]
 */
const fs = require('fs')
const path = require('path')
const { TraceMap, originalPositionFor } = require('@jridgewell/trace-mapping')

const file = process.argv[2]
const pairs = process.argv.slice(3)
const mapPath = path.join('dist/assets', file + '.map')
if (!fs.existsSync(mapPath)) {
  console.error('no sourcemap:', mapPath)
  process.exit(1)
}
const tracer = new TraceMap(JSON.parse(fs.readFileSync(mapPath, 'utf8')))

for (let i = 0; i + 1 < pairs.length; i += 2) {
  const line = Number(pairs[i])
  const column = Number(pairs[i + 1])
  const pos = originalPositionFor(tracer, { line, column })
  console.log(`${file}:${line}:${column}  →  ${pos.source ?? '?'}:${pos.line ?? '?'}:${pos.column ?? '?'}  ${pos.name ? '(' + pos.name + ')' : ''}`)
}
