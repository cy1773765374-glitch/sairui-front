import { defineStore } from 'pinia'

import { TOKEN_STORAGE_KEY } from '../api/client'
import {
  fetchMe,
  login as loginRequest,
  register as registerRequest,
  type LoginPayload,
  type RegisterPayload,
  type User,
} from '../api/auth'

const LOGIN_SOURCE_STORAGE_KEY = 'openclaw_userlook_login_source'

function getStoredLoginSource(): 'password' | 'wecom' {
  return localStorage.getItem(LOGIN_SOURCE_STORAGE_KEY) === 'wecom' ? 'wecom' : 'password'
}

interface AuthState {
  token: string
  user: User | null
  loginSource: 'password' | 'wecom'
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    token: localStorage.getItem(TOKEN_STORAGE_KEY) ?? '',
    user: null,
    loginSource: getStoredLoginSource(),
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.token && state.user),
    isAdmin: (state) => state.user?.role === 'admin',
  },
  actions: {
    setSession(token: string, user: User, loginSource: 'password' | 'wecom' = 'password') {
      this.token = token
      this.user = user
      this.loginSource = loginSource
      localStorage.setItem(TOKEN_STORAGE_KEY, token)
      localStorage.setItem(LOGIN_SOURCE_STORAGE_KEY, loginSource)
    },
    clearSession() {
      this.token = ''
      this.user = null
      this.loginSource = 'password'
      localStorage.removeItem(TOKEN_STORAGE_KEY)
      localStorage.removeItem(LOGIN_SOURCE_STORAGE_KEY)
    },
    async login(payload: LoginPayload) {
      const response = await loginRequest(payload)
      this.setSession(response.access_token, response.user, response.login_source ?? 'password')
    },
    async register(payload: RegisterPayload) {
      await registerRequest(payload)
    },
    async fetchCurrentUser() {
      this.user = await fetchMe()
    },
    logout() {
      this.clearSession()
    },
  },
})
