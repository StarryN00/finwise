import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'StatusTag.vue'), 'utf8')

describe('StatusTag', () => {
  it('resolves label reactively when async status props change', () => {
    expect(source).toContain("import { computed } from 'vue'")
    expect(source).toContain('const resolved = computed')
  })
})
