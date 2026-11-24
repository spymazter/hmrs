import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle, Check, CheckCircle2, ChevronDown, Inbox, Search, X } from 'lucide-react'

export function PageHead({ title, subtitle, actions }) {
  return (
    <div className="page-head">
      <div>
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-sub">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  )
}

export function Card({ title, subtitle, actions, children, className = '' }) {
  return (
    <div className={`card ${className}`}>
      {(title || actions) && (
        <div className="card-head">
          <div>
            {title && <h3 className="card-title">{title}</h3>}
            {subtitle && <p className="card-sub">{subtitle}</p>}
          </div>
          {actions}
        </div>
      )}
      <div className="card-body">{children}</div>
    </div>
  )
}

const STATUS_COLORS = {
  present: 'green', active: 'green', approved: 'green', processed: 'green', paid: 'green',
  in: 'green', live: 'green',
  absent: 'red', rejected: 'red', inactive: 'red', left: 'red', out: 'red', error: 'red',
  half_day: 'amber', pending: 'amber', draft: 'amber', generated: 'blue',
  leave: 'blue', week_off: 'blue', holiday: 'purple', break_in: 'blue', simulate: 'purple',
}

export function Badge({ status, children }) {
  const label = children ?? String(status ?? '').replace(/_/g, ' ')
  const color = STATUS_COLORS[status] || 'gray'
  return <span className={`badge badge-${color}`}>{label}</span>
}

export function SearchableSelect({
  value, onChange, options = [], placeholder = 'Select…', disabled = false,
  clearable = true, style, className = '', searchPlaceholder = 'Search…',
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const rootRef = useRef(null)
  const inputRef = useRef(null)

  const items = useMemo(
    () => options.map((opt) => typeof opt === 'object' ? opt : { value: opt, label: String(opt) }),
    [options],
  )
  const selected = items.find((opt) => String(opt.value) === String(value))
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return items
    return items.filter((opt) =>
      String(opt.label).toLowerCase().includes(q) || String(opt.value).toLowerCase().includes(q))
  }, [items, query])

  useEffect(() => {
    if (!open) return undefined
    rootRef.current?.querySelector('.search-select-menu')?.scrollTo(0, 0)
    inputRef.current?.focus()
    const onOutside = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onOutside)
    return () => document.removeEventListener('mousedown', onOutside)
  }, [open])

  const choose = (opt) => {
    onChange(opt.value)
    setQuery('')
    setOpen(false)
  }

  return (
    <div ref={rootRef} className={`search-select ${className}`} style={style}>
      <button type="button" className="search-select-trigger" disabled={disabled} onClick={() => setOpen((v) => !v)}>
        <span className={selected ? '' : 'muted'}>{selected?.label ?? placeholder}</span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="search-select-menu">
          <div className="search-select-search">
            <Search size={14} />
            <input ref={inputRef} value={query} onChange={(e) => setQuery(e.target.value)} placeholder={searchPlaceholder} />
          </div>
          <div className="search-select-list">
            {clearable && (
              <button type="button" className={`search-select-option ${value === '' || value == null ? 'selected' : ''}`} onClick={() => choose({ value: '' })}>
                <span>{placeholder}</span>
              </button>
            )}
            {filtered.map((opt) => (
              <button type="button" key={opt.value} className={`search-select-option ${String(opt.value) === String(value) ? 'selected' : ''}`} onClick={() => choose(opt)}>
                <span>{opt.label}</span>
                {String(opt.value) === String(value) && <Check size={13} />}
              </button>
            ))}
            {!filtered.length && <div className="search-select-empty">No matches</div>}
          </div>
        </div>
      )}
    </div>
  )
}

export function DataTable({ columns, rows, loading, emptyText = 'No records found' }) {
  if (loading) return <div className="loader">Loading…</div>
  if (!rows || rows.length === 0) {
    return <div className="empty"><Inbox size={30} /><div>{emptyText}</div></div>
  }
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{columns.map((col, i) => <th key={i} className={col.className || ''}>{col.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.id ?? i}>
              {columns.map((col, j) => (
                <td key={j} className={col.className || ''}>
                  {col.render ? col.render(row, i) : row[col.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Modal({ open, onClose, title, children, footer, width = 620, dismissible = true }) {
  if (!open) return null
  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (dismissible && e.target === e.currentTarget) onClose() }}>
      <div className="modal" style={{ maxWidth: width }}>
        <div className="modal-head">
          <div className="modal-title">{title}</div>
          {dismissible && <button className="close-x" onClick={onClose} aria-label="Close"><X size={18} /></button>}
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}

export function Field({ label, children, hint, full = false }) {
  return (
    <div className={`field ${full ? 'full' : ''}`}>
      <label>{label}</label>
      {children}
      {hint && <span className="hint">{hint}</span>}
    </div>
  )
}

export function Notice({ type = 'info', children }) {
  if (!children) return null
  const Icon = type === 'error' ? AlertCircle : CheckCircle2
  return <div className={`notice notice-${type}`}><Icon size={16} />{children}</div>
}

export function Stat({ icon, label, value, foot, color = '#4f46e5', to }) {
  const content = (
    <>
      <div className="kpi-icon" style={{ background: `${color}18`, color }}>{icon}</div>
      <div>
        <div className="kpi-value">{value ?? 0}</div>
        <div className="kpi-label">{label}</div>
        {foot && <div className="kpi-foot">{foot}</div>}
      </div>
    </>
  )
  if (to) {
    return <Link to={to} className="card kpi kpi-link" title={`View ${label.toLowerCase()}`}>{content}</Link>
  }
  return <div className="card kpi">{content}</div>
}

export const todayStr = () => new Date().toISOString().slice(0, 10)
export const monthStr = () => new Date().toISOString().slice(0, 7)
export const fmtTime = (value) => (value ? String(value).slice(11, 16) : '—')
export const fmtDate = (value) => (value ? String(value).slice(0, 10) : '—')
