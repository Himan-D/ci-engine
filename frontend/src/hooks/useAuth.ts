import { createContext, useContext, useState, useEffect, type ReactNode, createElement } from 'react'
import { authApi } from '../api/client'

interface AuthUser {
  username: string
  role: string
}

interface AuthContextType {
  user: AuthUser | null
  token: string | null
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<boolean>
  logout: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('ci_token'))
  const [user, setUser] = useState<AuthUser | null>(() => {
    const saved = localStorage.getItem('ci_user')
    return saved ? (JSON.parse(saved) as AuthUser) : null
  })

  useEffect(() => {
    if (token) {
      localStorage.setItem('ci_token', token)
    } else {
      localStorage.removeItem('ci_token')
    }
  }, [token])

  const login = async (username: string, password: string): Promise<boolean> => {
    try {
      const data = await authApi.login(username, password)
      setToken(data.access_token)
      const u: AuthUser = { username, role: 'developer' }
      setUser(u)
      localStorage.setItem('ci_user', JSON.stringify(u))
      return true
    } catch {
      return false
    }
  }

  const logout = () => {
    setToken(null)
    setUser(null)
    localStorage.removeItem('ci_token')
    localStorage.removeItem('ci_user')
  }

  return createElement(
    AuthContext.Provider,
    { value: { user, token, isAuthenticated: !!token, login, logout } },
    children,
  )
}

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
