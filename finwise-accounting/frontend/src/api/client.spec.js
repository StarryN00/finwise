import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'client.js'), 'utf8')

describe('api client', () => {
  it('uses extended timeouts for AI operations that can exceed the default request budget', () => {
    expect(source).toContain('AI_REQUEST_TIMEOUT_MS')
    expect(source).toContain('runAi: (packageId) => apiClient.post(`/monthly-packages/${packageId}/matching/ai-run`, undefined, { timeout: AI_REQUEST_TIMEOUT_MS })')
    expect(source).toContain('generateHealth: (packageId) => apiClient.post(`/monthly-packages/${packageId}/reports/health`, undefined, { timeout: AI_REQUEST_TIMEOUT_MS })')
  })
})
