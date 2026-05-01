import { useState, useEffect, useCallback } from 'react'
import { X, ChevronDown, ChevronUp, Trash2 } from 'lucide-react'
import { getNodeType, searchNodeTypes } from '../data/nodeTypes'
import type { Node } from '@xyflow/react'

interface NodePropertiesProps {
  node: Node | null
  onUpdate: (id: string, data: Record<string, unknown>) => void
  onDelete: (id: string) => void
  onClose: () => void
  allNodeLabels: string[]
}

function Field({
  label,
  children,
  hint,
}: {
  label: string
  children: React.ReactNode
  hint?: string
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label
        style={{
          display: 'block',
          fontSize: 10.5,
          color: '#71717a',
          textTransform: 'uppercase',
          letterSpacing: '0.07em',
          marginBottom: 5,
          fontFamily: '"Geist", "Inter", system-ui, sans-serif',
        }}
      >
        {label}
      </label>
      {children}
      {hint && (
        <p style={{ marginTop: 4, fontSize: 10, color: '#3f3f46' }}>{hint}</p>
      )}
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  background: '#0f0f11',
  border: '1px solid #2d2d30',
  borderRadius: 6,
  color: '#f4f4f5',
  fontSize: 12,
  padding: '7px 10px',
  outline: 'none',
  fontFamily: '"Geist", "Inter", system-ui, sans-serif',
  boxSizing: 'border-box',
}

const monoStyle: React.CSSProperties = {
  ...inputStyle,
  fontFamily: '"Geist Mono", ui-monospace, monospace',
  fontSize: 11.5,
  resize: 'vertical',
  minHeight: 90,
}

export function NodeProperties({ node, onUpdate, onDelete, onClose, allNodeLabels }: NodePropertiesProps) {
  const [data, setData] = useState<Record<string, unknown>>({})
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [nodeTypeQuery, setNodeTypeQuery] = useState('')
  const [showTypePicker, setShowTypePicker] = useState(false)

  useEffect(() => {
    if (node) setData({ ...(node.data as Record<string, unknown>) })
  }, [node?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const save = useCallback(
    (patch: Record<string, unknown>) => {
      if (!node) return
      const next = { ...data, ...patch }
      setData(next)
      onUpdate(node.id, next)
    },
    [node, data, onUpdate],
  )

  if (!node) {
    return (
      <div
        style={{
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#3f3f46',
          fontSize: 13,
          gap: 8,
          padding: 24,
          textAlign: 'center',
        }}
      >
        <span style={{ fontSize: 28 }}>☍</span>
        <span>Select a node to edit its properties</span>
        <span style={{ fontSize: 11 }}>Or double-click the canvas to add a node</span>
      </div>
    )
  }

  const nt = getNodeType((data.nodeType as string) ?? 'command')
  const typeResults = nodeTypeQuery ? searchNodeTypes(nodeTypeQuery) : searchNodeTypes('')

  return (
    <div
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        fontFamily: '"Geist", "Inter", system-ui, sans-serif',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '14px 16px',
          borderBottom: '1px solid #1f1f23',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          flexShrink: 0,
        }}
      >
        <div
          style={{
            width: 28,
            height: 28,
            borderRadius: 7,
            background: nt.bg,
            border: `1px solid ${nt.color}40`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 14,
          }}
        >
          {nt.emoji}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ color: '#f4f4f5', fontWeight: 600, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {(data.label as string) || 'Step'}
          </div>
          <div style={{ color: '#52525b', fontSize: 10 }}>{nt.label}</div>
        </div>
        <button
          onClick={() => { onDelete(node.id); onClose() }}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#3f3f46', padding: 4, borderRadius: 4 }}
          title="Delete node"
        >
          <Trash2 size={14} />
        </button>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#52525b', padding: 4, borderRadius: 4 }}
        >
          <X size={14} />
        </button>
      </div>

      {/* Form */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '16px',
          scrollbarWidth: 'thin',
          scrollbarColor: '#27272a transparent',
        }}
      >
        {/* Node type picker */}
        <Field label="Node Type">
          <div style={{ position: 'relative' }}>
            <div
              onClick={() => setShowTypePicker(!showTypePicker)}
              style={{
                ...inputStyle,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                cursor: 'pointer',
                paddingRight: 32,
                userSelect: 'none',
              }}
            >
              <span style={{ fontSize: 14 }}>{nt.emoji}</span>
              <span style={{ flex: 1, color: '#f4f4f5', fontSize: 12 }}>{nt.label}</span>
              <span
                style={{
                  position: 'absolute',
                  right: 10,
                  color: '#52525b',
                  display: 'flex',
                  alignItems: 'center',
                }}
              >
                {showTypePicker ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              </span>
            </div>

            {showTypePicker && (
              <div
                style={{
                  position: 'absolute',
                  top: '100%',
                  left: 0,
                  right: 0,
                  zIndex: 100,
                  background: '#0f0f11',
                  border: '1px solid #2d2d30',
                  borderRadius: 8,
                  boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
                  marginTop: 4,
                  overflow: 'hidden',
                }}
              >
                <input
                  value={nodeTypeQuery}
                  onChange={e => setNodeTypeQuery(e.target.value)}
                  placeholder="Search node type…"
                  style={{ ...inputStyle, border: 'none', borderBottom: '1px solid #1f1f23', borderRadius: 0 }}
                  // eslint-disable-next-line jsx-a11y/no-autofocus
                  autoFocus
                />
                <div style={{ maxHeight: 200, overflowY: 'auto' }}>
                  {typeResults.slice(0, 30).map(t => (
                    <div
                      key={t.type}
                      onClick={() => {
                        save({ nodeType: t.type, command: data.command || t.defaultCommand })
                        setShowTypePicker(false)
                        setNodeTypeQuery('')
                      }}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        padding: '7px 10px',
                        cursor: 'pointer',
                      }}
                      onMouseEnter={e => ((e.currentTarget as HTMLElement).style.background = '#1f1f23')}
                      onMouseLeave={e => ((e.currentTarget as HTMLElement).style.background = 'transparent')}
                    >
                      <span style={{ fontSize: 13 }}>{t.emoji}</span>
                      <span style={{ color: '#e4e4e7', fontSize: 12 }}>{t.label}</span>
                      <span style={{ marginLeft: 'auto', color: '#3f3f46', fontSize: 10 }}>{t.category}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Field>

        {/* Label */}
        <Field label="Label">
          <input
            value={(data.label as string) ?? ''}
            onChange={e => save({ label: e.target.value })}
            style={inputStyle}
            placeholder="Step name"
          />
        </Field>

        {/* Command */}
        {data.nodeType !== 'wait' && data.nodeType !== 'parallel' && (
          <Field
            label="Command"
            hint="Multi-line supported. Use ${{ env.VAR }} for expressions."
          >
            <textarea
              value={(data.command as string) ?? ''}
              onChange={e => save({ command: e.target.value })}
              style={{ ...monoStyle, display: 'block' }}
              placeholder={nt.defaultCommand}
              rows={4}
            />
          </Field>
        )}

        {/* Depends On */}
        <Field
          label="Depends On"
          hint="Click chips below or type comma-separated step labels."
        >
          <input
            value={(data.depends_on as string) ?? ''}
            onChange={e => save({ depends_on: e.target.value })}
            style={inputStyle}
            placeholder="Step A, Step B"
          />
          {allNodeLabels.filter(l => l !== (data.label as string)).length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
              {allNodeLabels
                .filter(l => l !== (data.label as string))
                .map(l => {
                  const current = ((data.depends_on as string) ?? '').split(',').map(x => x.trim()).filter(Boolean)
                  const active = current.includes(l)
                  return (
                    <button
                      key={l}
                      onClick={() => {
                        const next = active
                          ? current.filter(x => x !== l).join(', ')
                          : [...current, l].join(', ')
                        save({ depends_on: next })
                      }}
                      style={{
                        padding: '2px 8px',
                        borderRadius: 4,
                        border: '1px solid',
                        borderColor: active ? '#a78bfa' : '#2d2d30',
                        background: active ? '#2e1065' : 'transparent',
                        color: active ? '#c4b5fd' : '#71717a',
                        fontSize: 11,
                        cursor: 'pointer',
                        fontFamily: '"Geist Mono", ui-monospace, monospace',
                      }}
                    >
                      {l}
                    </button>
                  )
                })}
            </div>
          )}
        </Field>

        {/* Advanced toggle */}
        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          style={{
            width: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'none',
            border: '1px solid #1f1f23',
            borderRadius: 6,
            color: '#52525b',
            fontSize: 11.5,
            padding: '7px 10px',
            cursor: 'pointer',
            marginBottom: showAdvanced ? 14 : 0,
          }}
        >
          Advanced Options
          {showAdvanced ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </button>

        {showAdvanced && (
          <div style={{ marginTop: 14 }}>
            <Field label="Timeout (minutes)">
              <input
                type="number"
                value={(data.timeout as number) ?? ''}
                onChange={e => save({ timeout: Number(e.target.value) })}
                style={inputStyle}
                placeholder="60"
                min={1}
              />
            </Field>

            <Field label="Max Retries">
              <input
                type="number"
                value={(data.maxRetries as number) ?? ''}
                onChange={e => save({ maxRetries: Number(e.target.value) })}
                style={inputStyle}
                placeholder="0"
                min={0}
                max={10}
              />
            </Field>

            <Field label="Priority">
              <input
                type="number"
                value={(data.priority as number) ?? ''}
                onChange={e => save({ priority: Number(e.target.value) })}
                style={inputStyle}
                placeholder="0"
              />
            </Field>

            <Field label="Required Agent Tags" hint="Comma-separated. e.g. docker, linux">
              <input
                value={(data.required_tags as string) ?? ''}
                onChange={e => save({ required_tags: e.target.value })}
                style={inputStyle}
                placeholder="docker, linux"
              />
            </Field>

            <Field label="Environment Variables" hint="KEY=VALUE one per line">
              <textarea
                value={(data.env_raw as string) ?? ''}
                onChange={e => save({ env_raw: e.target.value })}
                style={{ ...monoStyle, display: 'block' }}
                placeholder={'NODE_ENV=production\nDEBUG=false'}
                rows={3}
              />
            </Field>

            <Field label="Working Directory">
              <input
                value={(data.working_dir as string) ?? ''}
                onChange={e => save({ working_dir: e.target.value })}
                style={inputStyle}
                placeholder="/workspace"
              />
            </Field>

            <Field label="Condition (if:)" hint="e.g. ${{ success() }}">
              <input
                value={(data.skip_condition as string) ?? ''}
                onChange={e => save({ skip_condition: e.target.value })}
                style={inputStyle}
                placeholder="${{ success() }}"
              />
            </Field>

            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
              <input
                id="cont-err"
                type="checkbox"
                checked={!!(data.continueOnError as boolean)}
                onChange={e => save({ continueOnError: e.target.checked })}
                style={{ cursor: 'pointer' }}
              />
              <label htmlFor="cont-err" style={{ color: '#a1a1aa', fontSize: 12, cursor: 'pointer' }}>
                Continue on error
              </label>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
