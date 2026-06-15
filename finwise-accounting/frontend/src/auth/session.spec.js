// @vitest-environment happy-dom

import { beforeEach, describe, expect, it } from 'vitest'
import {
  AUTH_TOKEN_KEY,
  AUTH_USER_KEY,
  clearAuthSession,
  getAuthToken,
  getAuthUser,
  isAuthenticated,
  setAuthSession,
} from './session'

describe('auth session storage', () => {
  beforeEach(() => {
    const store = new Map()
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (key) => store.get(key) ?? null,
        setItem: (key, value) => store.set(key, String(value)),
        removeItem: (key) => store.delete(key),
        clear: () => store.clear(),
      },
    })
  })

  it('stores and clears the current operator session', () => {
    expect(isAuthenticated()).toBe(false)

    setAuthSession('token-1', 'operator')
    expect(window.localStorage.getItem(AUTH_TOKEN_KEY)).toBe('token-1')
    expect(window.localStorage.getItem(AUTH_USER_KEY)).toBe('operator')
    expect(getAuthToken()).toBe('token-1')
    expect(getAuthUser()).toBe('operator')
    expect(isAuthenticated()).toBe(true)

    clearAuthSession()
    expect(getAuthToken()).toBe('')
    expect(getAuthUser()).toBe('')
    expect(isAuthenticated()).toBe(false)
  })
})
