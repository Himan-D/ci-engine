import { useEffect, useState } from 'react'
import { metadataApi, type BuildMetadataItem } from '../api/client'
import { Database, Copy, Check } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <button
      onClick={handleCopy}
      className="text-zinc-700 hover:text-zinc-400 transition-colors p-0.5 rounded"
      title="Copy value"
    >
      {copied ? <Check size={10} className="text-green-400" /> : <Copy size={10} />}
    </button>
  )
}

interface BuildMetadataPanelProps {
  buildId: number
}

export function BuildMetadataPanel({ buildId }: BuildMetadataPanelProps) {
  const [items, setItems] = useState<BuildMetadataItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    metadataApi.list(buildId)
      .then(res => setItems(res.metadata))
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }, [buildId])

  if (loading) {
    return <div className="h-16 bg-zinc-800/60 rounded-lg animate-pulse" />
  }

  if (items.length === 0) return null

  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <Database size={12} className="text-zinc-600" />
        <span className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">
          Build Metadata
        </span>
        <span className="text-xs bg-zinc-800 text-zinc-400 px-1.5 py-0.5 rounded font-mono">
          {items.length}
        </span>
      </div>
      <div className="card overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-zinc-800/60">
              <th className="text-left px-3 py-2 text-zinc-600 font-medium">Key</th>
              <th className="text-left px-3 py-2 text-zinc-600 font-medium">Value</th>
              <th className="text-left px-3 py-2 text-zinc-600 font-medium hidden sm:table-cell">Set</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, i) => (
              <tr
                key={item.id}
                className={`border-b border-zinc-800/30 last:border-0 ${
                  i % 2 === 0 ? '' : 'bg-zinc-800/20'
                }`}
              >
                <td className="px-3 py-2">
                  <code className="text-brand-400 font-mono">{item.key}</code>
                </td>
                <td className="px-3 py-2 max-w-xs">
                  <div className="flex items-center gap-1.5">
                    <code className="text-zinc-300 font-mono truncate">{item.value}</code>
                    <CopyButton text={item.value} />
                  </div>
                </td>
                <td className="px-3 py-2 text-zinc-600 hidden sm:table-cell">
                  {item.updated_at
                    ? formatDistanceToNow(new Date(item.updated_at), { addSuffix: true })
                    : item.created_at
                      ? formatDistanceToNow(new Date(item.created_at), { addSuffix: true })
                      : '—'
                  }
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
