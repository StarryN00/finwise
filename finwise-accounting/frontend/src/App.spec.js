import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'App.vue'), 'utf8')

describe('App auth layout', () => {
  it('renders public pages without the operator workbench shell', () => {
    expect(source).toContain('route.meta.publicLayout')
    expect(source).toContain('<router-view v-if="isPublicLayout" />')
    expect(source).toContain('<AppLayout v-else>')
  })

  it('does not load workspace data while showing public pages', () => {
    expect(source).toContain('watch(')
    expect(source).toContain('workspace.loadWorkspace()')
    expect(source).toContain('if (!publicLayout)')
  })
})
