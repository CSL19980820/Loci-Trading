/**
 * Monaco workers（Vite `?worker`）。
 * monaco-editor 0.56 的 exports 把 `monaco-editor/<path>.js` 映到 `esm/vs/<path>.js`，
 * 不要写 `monaco-editor/esm/vs/...`（会双倍路径）。
 */
import editorWorker from 'monaco-editor/editor/editor.worker.js?worker'
import jsonWorker from 'monaco-editor/language/json/json.worker.js?worker'

let configured = false

export function ensureMonacoEnv(): void {
  if (configured) return
  configured = true
  ;(globalThis as typeof globalThis & { MonacoEnvironment?: object }).MonacoEnvironment = {
    getWorker(_: unknown, label: string) {
      if (label === 'json') return new jsonWorker()
      return new editorWorker()
    },
  }
}
