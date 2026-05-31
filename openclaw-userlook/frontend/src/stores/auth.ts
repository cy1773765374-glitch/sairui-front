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

interface AuthState {
  token: string
  user: User | null
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    token: localStorage.getItem(TOKEN_STORAGE_KEY) ?? '',
    user: null,
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.token && state.user),
    isAdmin: (state) => state.user?.role === 'admin',
  },
  actions: {
    setSession(token: string, user: User) {
      this.token = token
      this.user = user
      localStorage.setItem(TOKEN_STORAGE_KEY, token)
    },
    clearSession() {
      this.token = ''
      this.user = null
      localStorage.removeItem(TOKEN_STORAGE_KEY)
    },
    async login(payload: LoginPayload) {
      const response = await loginRequest(payload)
      this.setSession(response.access_token, response.user)
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
