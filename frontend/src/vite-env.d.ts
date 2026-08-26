/// <reference types="vite/client" />

declare module '*?worker' {
  const workerConstructor: {
    new (): Worker
  }
  export default workerConstructor
}

declare module 'monaco-editor-css'

declare module 'vue-element-plus-x/es/Thinking/index.js' {
  import type { DefineComponent } from 'vue'
  const Thinking: DefineComponent<Record<string, unknown>, object, object>
  export default Thinking
}

declare module 'vue-element-plus-x/es/XSender/index.js' {
  import type { DefineComponent } from 'vue'
  const XSender: DefineComponent<Record<string, unknown>, object, object>
  export default XSender
}
