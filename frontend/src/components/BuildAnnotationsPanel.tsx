import { useEffect, useState } from 'react'
import { annotationsApi, type BuildAnnotation, type AnnotationStyle } from '../api/client'
import type { LucideIcon } from 'lucide-react'
import { Info, AlertTriangle, CheckCircle2, XCircle, ChevronDown, ChevronUp } from 'lucide-react'

const STYLE_CONFIG: Record<AnnotationStyle, {
  bg: string; border: string; text: string; iconColor: string; label: string
}> = {
  success: {
    bg: 'bg-green-950/40', border: 'border-green-800/60', text: 'text-green-200',
    iconColor: 'text-green-400', label: 'Success',
  },
  warning: {
    bg: 'bg-amber-950/40', border: 'border-amber-800/60', text: 'text-amber-200',
    iconColor: 'text-amber-400', label: 'Warning',
  },
  error: {
    bg: 'bg-red-950/40', border: 'border-red-800/60', text: 'text-red-200',
    iconColor: 'text-red-400', label: 'Error',
  },
  info: {
    bg: 'bg-blue-950/40', border: 'border-blue-800/60', text: 'text-blue-200',
    iconColor: 'text-blue-400', label: 'Info',
  },
}

const STYLE_ICONS: Record<AnnotationStyle, LucideIcon> = {
  success: CheckCircle2,
  warning: AlertTriangle,
  error:   XCircle,
  info:    Info,
}

// Minimal HTML sanitizer — strips script/iframe but allows formatting tags
// These annotations come from authenticated CI agents so this is best-effort
function sanitizeHtml(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<iframe[\s\S]*?<\/iframe>/gi, '')
    .replace(/on\w+="[^"]*"/gi, '')
    .replace(/on\w+='[^']*'/gi, '')
    .replace(/javascript:/gi, '')
}

interface AnnotationBlockProps {
  annotation: BuildAnnotation
}

function AnnotationBlock({ annotation }: AnnotationBlockProps) {
  const [expanded, setExpanded] = useState(true)
  const cfg = STYLE_CONFIG[annotation.style] ?? STYLE_CONFIG.info
  const Icon: LucideIcon = STYLE_ICONS[annotation.style] ?? Info

  return (
    <div className={`rounded-lg border ${cfg.bg} ${cfg.border} overflow-hidden`}>
      <button
        onClick={() => setExpanded(e => !e)}
        className={`w-full flex items-center gap-2.5 px-3.5 py-2.5 text-left hover:bg-white/5 transition-colors`}
      >
        <Icon size={14} className={`flex-shrink-0 ${cfg.iconColor}`} />
        <span className={`flex-1 text-xs font-semibold font-mono tracking-wide uppercase ${cfg.iconColor}`}>
          {annotation.context}
        </span>
        <span className="text-zinc-600 text-xs">{cfg.label}</span>
        {expanded
          ? <ChevronUp size={12} className="text-zinc-600 flex-shrink-0" />
          : <ChevronDown size={12} className="text-zinc-600 flex-shrink-0" />
        }
      </button>
      {expanded && (
        <div
          className={`px-4 py-3 text-sm ${cfg.text} border-t ${cfg.border} annotation-body`}
          // trusted content from authenticated CI agents
          dangerouslySetInnerHTML={{ __html: sanitizeHtml(annotation.body_html) }}
        />
      )}
    </div>
  )
}

interface BuildAnnotationsPanelProps {
  buildId: number
}

export function BuildAnnotationsPanel({ buildId }: BuildAnnotationsPanelProps) {
  const [annotations, setAnnotations] = useState<BuildAnnotation[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    annotationsApi.list(buildId)
      .then(res => setAnnotations(res.annotations))
      .catch(() => setAnnotations([]))
      .finally(() => setLoading(false))
  }, [buildId])

  if (loading) {
    return (
      <div className="space-y-2">
        <div className="h-12 bg-zinc-800/60 rounded-lg animate-pulse" />
        <div className="h-12 bg-zinc-800/60 rounded-lg animate-pulse" />
      </div>
    )
  }

  if (annotations.length === 0) return null

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">
          Annotations
        </span>
        <span className="text-xs bg-zinc-800 text-zinc-400 px-1.5 py-0.5 rounded font-mono">
          {annotations.length}
        </span>
      </div>
      {annotations.map(a => (
        <AnnotationBlock key={a.id} annotation={a} />
      ))}
    </div>
  )
}
