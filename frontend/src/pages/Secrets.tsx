import { useEffect, useState, useCallback, type FormEvent } from 'react'
import { KeyRound, Plus, Trash2, RefreshCw, Eye, EyeOff, AlertCircle } from 'lucide-react'
import { secretsApi, type Secret } from '../api/client'
import { format } from 'date-fns'

interface NewSecretForm {
  name: string
  value: string
  description: string
}

const EMPTY_FORM: NewSecretForm = { name: '', value: '', description: '' }

export default function Secrets() {
  const [secrets, setSecrets]   = useState<Secret[]>([])
  const [loading, setLoading]   = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm]         = useState<NewSecretForm>(EMPTY_FORM)
  const [showValue, setShowValue] = useState(false)
  const [saving, setSaving]     = useState(false)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [error, setError]       = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    secretsApi.list()
      .then(s => { setSecrets(s); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault()
    if (!form.name.trim() || !form.value.trim()) return
    setSaving(true)
    setError(null)
    try {
      await secretsApi.create({
        name: form.name.trim().toUpperCase().replace(/\s+/g, '_'),
        value: form.value,
        description: form.description.trim() || undefined,
      })
      setForm(EMPTY_FORM)
      setShowForm(false)
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: number) => {
    if (confirmDelete !== id) {
      setConfirmDelete(id)
      return
    }
    setDeleting(id)
    setConfirmDelete(null)
    try {
      await secretsApi.delete(id)
      load()
    } finally {
      setDeleting(null)
    }
  }

  return (
    <div className="p-6 max-w-4xl mx-auto animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-display font-bold text-zinc-100">Secrets</h1>
          <p className="text-sm text-zinc-500 mt-0.5">
            Encrypted at rest · {secrets.length} secret{secrets.length !== 1 ? 's' : ''}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={load} className="btn-secondary btn-sm" disabled={loading}>
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          </button>
          <button onClick={() => setShowForm(v => !v)} className="btn-primary btn-sm">
            <Plus size={13} />
            Add Secret
          </button>
        </div>
      </div>

      {/* Add secret form */}
      {showForm && (
        <div className="card p-5 mb-6 animate-fade-in">
          <h2 className="text-sm font-semibold text-zinc-300 mb-4">New Secret</h2>
          <form onSubmit={handleCreate} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-zinc-500 mb-1.5 uppercase tracking-wider">
                  Name <span className="text-zinc-700">(becomes env var)</span>
                </label>
                <input
                  className="input font-mono uppercase"
                  placeholder="MY_SECRET_KEY"
                  value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  required
                />
              </div>
              <div>
                <label className="block text-xs text-zinc-500 mb-1.5 uppercase tracking-wider">
                  Description <span className="text-zinc-700">(optional)</span>
                </label>
                <input
                  className="input"
                  placeholder="What is this secret for?"
                  value={form.description}
                  onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                />
              </div>
            </div>
            <div>
              <label className="block text-xs text-zinc-500 mb-1.5 uppercase tracking-wider">
                Value
              </label>
              <div className="relative">
                <input
                  className="input pr-10 font-mono"
                  type={showValue ? 'text' : 'password'}
                  placeholder="secret-value"
                  value={form.value}
                  onChange={e => setForm(f => ({ ...f, value: e.target.value }))}
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowValue(v => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-600 hover:text-zinc-400 transition-colors"
                >
                  {showValue ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
              <p className="text-xs text-zinc-700 mt-1">
                Value is Fernet-encrypted before storage and never returned in API responses.
              </p>
            </div>

            {error && (
              <div className="flex items-center gap-2 text-red-400 text-sm bg-red-900/20 border border-red-800/40 rounded-lg px-3 py-2">
                <AlertCircle size={14} />
                {error}
              </div>
            )}

            <div className="flex gap-2 justify-end pt-1">
              <button
                type="button"
                onClick={() => { setShowForm(false); setForm(EMPTY_FORM); setError(null) }}
                className="btn-secondary btn-sm"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saving}
                className="btn-primary btn-sm disabled:opacity-50"
              >
                {saving ? (
                  <><span className="w-3 h-3 border border-white/30 border-t-white rounded-full animate-spin" /> Saving…</>
                ) : (
                  <><Plus size={12} /> Save Secret</>
                )}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Secrets table */}
      <div className="card overflow-hidden">
        <div className="grid grid-cols-[1fr_2fr_140px_80px] gap-4 px-5 py-3 bg-zinc-900/80 border-b border-zinc-800 text-xs font-medium text-zinc-500 uppercase tracking-wider">
          <div>Name</div>
          <div>Description</div>
          <div>Created</div>
          <div className="text-right">Actions</div>
        </div>

        {loading ? (
          <div className="divide-y divide-zinc-800/60">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="grid grid-cols-[1fr_2fr_140px_80px] gap-4 px-5 py-4 animate-pulse">
                <div className="h-4 bg-zinc-800 rounded w-3/4" />
                <div className="h-4 bg-zinc-800 rounded w-1/2" />
                <div className="h-4 bg-zinc-800 rounded w-20" />
                <div className="h-4 bg-zinc-800 rounded w-8 ml-auto" />
              </div>
            ))}
          </div>
        ) : secrets.length === 0 ? (
          <div className="py-16 text-center">
            <KeyRound size={32} className="text-zinc-700 mx-auto mb-3" />
            <p className="text-sm text-zinc-500">No secrets configured</p>
            <button onClick={() => setShowForm(true)} className="btn-primary btn-sm mt-4 mx-auto">
              Add your first secret
            </button>
          </div>
        ) : (
          <div className="divide-y divide-zinc-800/40">
            {secrets.map(secret => (
              <div
                key={secret.id}
                className="grid grid-cols-[1fr_2fr_140px_80px] gap-4 px-5 py-3.5 items-center hover:bg-zinc-800/20 transition-colors"
              >
                {/* Name */}
                <div className="flex items-center gap-2 min-w-0">
                  <KeyRound size={12} className="text-zinc-600 flex-shrink-0" />
                  <code className="text-sm font-mono text-zinc-200 truncate">
                    {secret.name}
                  </code>
                  {!secret.is_active && (
                    <span className="text-xs text-zinc-600 bg-zinc-800 px-1.5 py-0.5 rounded flex-shrink-0">
                      inactive
                    </span>
                  )}
                </div>

                {/* Description */}
                <span className="text-sm text-zinc-500 truncate">
                  {secret.description || <span className="text-zinc-700">—</span>}
                </span>

                {/* Created */}
                <span className="text-xs text-zinc-600">
                  {format(new Date(secret.created_at), 'MMM d, yyyy')}
                </span>

                {/* Actions */}
                <div className="flex justify-end">
                  {confirmDelete === secret.id ? (
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => setConfirmDelete(null)}
                        className="text-xs text-zinc-500 hover:text-zinc-300 px-2 py-1"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => handleDelete(secret.id)}
                        className="text-xs text-red-400 hover:text-red-300 px-2 py-1 font-medium"
                      >
                        Delete
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => handleDelete(secret.id)}
                      disabled={deleting === secret.id}
                      className="p-1.5 text-zinc-700 hover:text-red-400 hover:bg-red-900/20 rounded transition-colors disabled:opacity-50"
                      title="Delete secret"
                    >
                      <Trash2 size={13} />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
