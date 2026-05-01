import { useState, useEffect, useRef, useCallback } from 'react'
import { Search } from 'lucide-react'
import { ALL_NODE_TYPES, NODE_CATEGORIES, searchNodeTypes, type NodeTypeDef } from '../data/nodeTypes'

interface NodePickerProps {
  position?: { x: number; y: number }
  onSelect: (nodeType: NodeTypeDef) => void
  onClose: () => void
  /** If true renders as an embedded panel rather than a floating overlay */
  embedded?: boolean
  initialQuery?: string
}

export function NodePicker({ position, onSelect, onClose, embedded, initialQuery = '' }: NodePickerProps) {
  const [query, setQuery] = useState(initialQuery)
  const [activeCategory, setActiveCategory] = useState<string | null>(null)
  const [highlighted, setHighlighted] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const results = query
    ? searchNodeTypes(query)
    : activeCategory
    ? ALL_NODE_TYPES.filter(n => n.category === activeCategory)
    : ALL_NODE_TYPES.slice(0, 20)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  useEffect(() => {
    setHighlighted(0)
  }, [query, activeCategory])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') { onClose(); return }
      if (e.key === 'ArrowDown') { e.preventDefault(); setHighlighted(h => Math.min(h + 1, results.length - 1)) }
      if (e.key === 'ArrowUp')   { e.preventDefault(); setHighlighted(h => Math.max(h - 1, 0)) }
      if (e.key === 'Enter' && results[highlighted]) {
        e.preventDefault()
        onSelect(results[highlighted])
      }
    },
    [results, highlighted, onSelect, onClose],
  )

  const content = (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: embedded ? '100%' : 480,
        width: embedded ? '100%' : 360,
        background: '#0f0f11',
        border: embedded ? 'none' : '1px solid #2d2d30',
        borderRadius: embedded ? 0 : 14,
        overflow: 'hidden',
        boxShadow: embedded ? 'none' : '0 24px 64px rgba(0,0,0,0.6)',
      }}
    >
      {/* Search */}
      <div
        style={{
          padding: '12px 14px',
          borderBottom: '1px solid #1f1f23',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <Search size={14} color="#52525b" />
        <input
          ref={inputRef}
          value={query}
          onChange={e => { setQuery(e.target.value); setActiveCategory(null) }}
          onKeyDown={handleKeyDown}
          placeholder="Search nodes… or type /"
          style={{
            flex: 1,
            background: 'transparent',
            border: 'none',
            outline: 'none',
            color: '#f4f4f5',
            fontSize: 13,
            fontFamily: '"Geist", "Inter", system-ui, sans-serif',
          }}
        />
        {!embedded && (
          <kbd
            style={{
              fontSize: 10,
              color: '#3f3f46',
              background: '#18181b',
              border: '1px solid #2d2d30',
              borderRadius: 4,
              padding: '2px 6px',
            }}
          >
            ESC
          </kbd>
        )}
      </div>

      {/* Category pills */}
      {!query && (
        <div
          style={{
            display: 'flex',
            gap: 6,
            padding: '10px 14px',
            overflowX: 'auto',
            borderBottom: '1px solid #1f1f23',
            scrollbarWidth: 'none',
          }}
        >
          <button
            onClick={() => setActiveCategory(null)}
            style={{
              padding: '3px 10px',
              borderRadius: 20,
              border: '1px solid',
              borderColor: !activeCategory ? '#a78bfa' : '#2d2d30',
              background: !activeCategory ? '#2e1065' : 'transparent',
              color: !activeCategory ? '#c4b5fd' : '#71717a',
              fontSize: 11,
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              transition: 'all 0.1s',
            }}
          >
            All
          </button>
          {NODE_CATEGORIES.map(cat => (
            <button
              key={cat}
              onClick={() => setActiveCategory(activeCategory === cat ? null : cat)}
              style={{
                padding: '3px 10px',
                borderRadius: 20,
                border: '1px solid',
                borderColor: activeCategory === cat ? '#a78bfa' : '#2d2d30',
                background: activeCategory === cat ? '#2e1065' : 'transparent',
                color: activeCategory === cat ? '#c4b5fd' : '#71717a',
                fontSize: 11,
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                transition: 'all 0.1s',
              }}
            >
              {cat}
            </button>
          ))}
        </div>
      )}

      {/* Results */}
      <div
        ref={listRef}
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '6px 8px',
          scrollbarWidth: 'thin',
          scrollbarColor: '#27272a transparent',
        }}
      >
        {results.length === 0 && (
          <div style={{ color: '#3f3f46', fontSize: 12, textAlign: 'center', padding: '32px 0' }}>
            No nodes match "{query}"
          </div>
        )}

        {results.map((nt, i) => (
          <div
            key={nt.type}
            onClick={() => onSelect(nt)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '8px 10px',
              borderRadius: 8,
              cursor: 'pointer',
              background: i === highlighted ? '#1f1f23' : 'transparent',
              transition: 'background 0.1s',
            }}
            onMouseEnter={() => setHighlighted(i)}
          >
            {/* Emoji icon with colored bg */}
            <div
              style={{
                width: 34,
                height: 34,
                borderRadius: 8,
                background: nt.bg,
                border: `1px solid ${nt.color}40`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 16,
                flexShrink: 0,
              }}
            >
              {nt.emoji}
            </div>

            {/* Info */}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  color: '#f4f4f5',
                  fontSize: 12.5,
                  fontWeight: 600,
                  fontFamily: '"Geist", "Inter", system-ui, sans-serif',
                }}
              >
                {nt.label}
              </div>
              <div style={{ color: '#52525b', fontSize: 11, marginTop: 1 }}>
                {nt.description}
              </div>
            </div>

            {/* Category badge */}
            <span
              style={{
                fontSize: 10,
                color: nt.color,
                background: `${nt.color}15`,
                border: `1px solid ${nt.color}25`,
                borderRadius: 4,
                padding: '2px 6px',
                flexShrink: 0,
                fontFamily: '"Geist Mono", ui-monospace, monospace',
              }}
            >
              {nt.category}
            </span>
          </div>
        ))}
      </div>

      {!embedded && (
        <div
          style={{
            padding: '8px 14px',
            borderTop: '1px solid #1f1f23',
            display: 'flex',
            gap: 12,
            alignItems: 'center',
          }}
        >
          <span style={{ color: '#3f3f46', fontSize: 10 }}>
            <kbd style={{ color: '#52525b' }}>↑↓</kbd> navigate &nbsp;
            <kbd style={{ color: '#52525b' }}>↵</kbd> select
          </span>
          <span style={{ color: '#27272a', fontSize: 10, marginLeft: 'auto' }}>
            {results.length} node{results.length !== 1 ? 's' : ''}
          </span>
        </div>
      )}
    </div>
  )

  if (embedded) return content

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'center',
        paddingTop: position ? 0 : 120,
        background: 'rgba(0,0,0,0.5)',
        backdropFilter: 'blur(2px)',
      }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        style={
          position
            ? {
                position: 'absolute',
                left: Math.min(position.x, window.innerWidth - 380),
                top: Math.min(position.y, window.innerHeight - 500),
              }
            : {}
        }
      >
        {content}
      </div>
    </div>
  )
}
