import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Hammer,
  GitBranch,
  Bot,
  KeyRound,
  Zap,
  LogOut,
  ChevronRight,
  BarChart3,
} from 'lucide-react'
import { useAuth } from '../hooks/useAuth'

const NAV = [
  { to: '/dashboard',  icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/builds',     icon: Hammer,          label: 'Builds'    },
  { to: '/pipeline',   icon: GitBranch,       label: 'Pipeline'  },
  { to: '/agents',     icon: Bot,             label: 'Agents'    },
  { to: '/secrets',    icon: KeyRound,        label: 'Secrets'   },
  { to: '/analytics',  icon: BarChart3,       label: 'Analytics' },
]

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <aside className="w-56 flex-shrink-0 flex flex-col bg-zinc-950/80 border-r border-zinc-800/70 backdrop-blur-sm">
        {/* Logo */}
        <div className="flex items-center gap-2.5 px-4 py-5 border-b border-zinc-800/50">
          <div className="w-8 h-8 rounded-lg bg-brand-500/15 border border-brand-500/30 flex items-center justify-center flex-shrink-0">
            <Zap size={16} className="text-brand-500" />
          </div>
          <span className="font-display font-bold text-zinc-100 tracking-tight text-lg leading-none">
            CI Engine
          </span>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 py-4 space-y-0.5">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `nav-item ${isActive ? 'active' : ''}`
              }
            >
              <Icon size={16} className="nav-icon flex-shrink-0" />
              {label}
              {/* active indicator */}
              <ChevronRight
                size={12}
                className="ml-auto opacity-0 group-[.active]:opacity-100 text-zinc-600 transition-opacity"
              />
            </NavLink>
          ))}
        </nav>

        {/* User */}
        <div className="px-2 pb-4 border-t border-zinc-800/50 pt-3">
          <div className="flex items-center gap-2.5 px-3 py-2">
            <div className="w-7 h-7 rounded-full bg-brand-500/20 border border-brand-500/30 flex items-center justify-center flex-shrink-0">
              <span className="text-brand-400 text-xs font-bold font-display uppercase">
                {user?.username?.[0] ?? 'U'}
              </span>
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-zinc-200 truncate">{user?.username ?? 'user'}</div>
              <div className="text-xs text-zinc-600 capitalize">{user?.role ?? 'developer'}</div>
            </div>
            <button
              onClick={handleLogout}
              className="text-zinc-600 hover:text-zinc-300 transition-colors p-1 rounded"
              title="Sign out"
            >
              <LogOut size={14} />
            </button>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-hidden flex flex-col">
        <Outlet />
      </main>
    </div>
  )
}
