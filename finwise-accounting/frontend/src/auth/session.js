export const AUTH_TOKEN_KEY = 'finwise.auth.token'
export const AUTH_USER_KEY = 'finwise.auth.user'

function getStorage() {
  if (typeof window === 'undefined') {
    return null
  }
  return window.localStorage
}

export function setAuthSession(token, username) {
  const storage = getStorage()
  if (!storage) {
    return
  }
  storage.setItem(AUTH_TOKEN_KEY, token)
  storage.setItem(AUTH_USER_KEY, username || '')
}

export function getAuthToken() {
  return getStorage()?.getItem(AUTH_TOKEN_KEY) || ''
}

export function getAuthUser() {
  return getStorage()?.getItem(AUTH_USER_KEY) || ''
}

export function isAuthenticated() {
  return Boolean(getAuthToken())
}

export function clearAuthSession() {
  const storage = getStorage()
  if (!storage) {
    return
  }
  storage.removeItem(AUTH_TOKEN_KEY)
  storage.removeItem(AUTH_USER_KEY)
}
