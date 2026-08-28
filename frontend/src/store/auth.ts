import { create } from 'zustand'

interface AuthState {
  authenticated: boolean
  username: string
  ready: boolean
  setAuth: (authenticated: boolean, username: string) => void
}

export const useAuth = create<AuthState>((set) => ({
  authenticated: false,
  username: '',
  ready: false,
  setAuth: (authenticated, username) => set({ authenticated, username, ready: true }),
}))
