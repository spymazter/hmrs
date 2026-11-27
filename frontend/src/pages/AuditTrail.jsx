import { useEffect, useState } from 'react'
import { History, RefreshCw, Search } from 'lucide-react'
import api, { errorMessage } from '../api'
import { Card, DataTable, Field, Modal, Notice, PageHead, SearchableSelect } from '../components/ui'

const EMPTY_FILTERS = { user_id: '', action: '', entity: '', from_date: '', to_date: '' }

function stamp(value) {
  return value ? String(value).replace('T', ' ').slice(0, 19) : '—'
}

function bodySummary(details) {
  const body = details?.body
  if (!body || (typeof body === 'object' && !Object.keys(body).length)) return '—'
  const text = typeof body === 'string' ? body : JSON.stringify(body)
  return text.length > 140 ? `${text.slice(0, 140)}…` : text
}

export default function AuditTrail() {
  const [rows, setRows] = useState([])
  const [users, setUsers] = useState([])
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get('/access/users').then((r) => setUsers(r.data || [])).catch(() => {})
  }, [])

  const load = () => {
    const params = new URLSearchParams({ limit: '200' })
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.set(key, String(value))
    })
    api.get(`/audit/logs?${params}`)
      .then((r) => { setRows(r.data); setError('') })
      .catch((err) => setError(errorMessage(err)))
  }

  useEffect(() => { load() }, [filters])

  const setFilter = (key, value) => setFilters((current) => ({ ...current, [key]: value }))

  const userOptions = [
    { value: '', label: 'All users' },
    ...users.map((user) => ({
      value: user.id,
      label: `${user.username}${user.full_name ? ` — ${user.full_name}` : ''}`,
    })),
  ]

  return (
    <>
      <PageHead
        title="Audit trail"
        subtitle="Who changed what — every successful add, edit and delete is recorded"
        actions={<button className="btn btn-outline" onClick={load}><RefreshCw size={15} /> Refresh</button>}
      />
      <Notice type="error">{error}</Notice>

      <Card title="Filters" subtitle="Narrow the change log by user, action, module or date">
        <div className="toolbar">
          <div className="field-inline"><label>User</label>
            <SearchableSelect
              value={filters.user_id}
              onChange={(value) => setFilter('user_id', value)}
              options={userOptions}
              placeholder="All users"
              searchPlaceholder="Search users…"
              style={{ width: 220 }}
            />
          </div>
          <div className="field-inline"><label>Action</label><input value={filters.action} onChange={(e) => setFilter('action', e.target.value)} placeholder="employees, payroll…" style={{ width: 180 }} /></div>
          <div className="field-inline"><label>Module</label><input value={filters.entity} onChange={(e) => setFilter('entity', e.target.value)} placeholder="employees" style={{ width: 160 }} /></div>
          <div className="field-inline"><label>From</label><input type="date" value={filters.from_date} onChange={(e) => setFilter('from_date', e.target.value)} style={{ width: 150 }} /></div>
          <div className="field-inline"><label>To</label><input type="date" value={filters.to_date} onChange={(e) => setFilter('to_date', e.target.value)} style={{ width: 150 }} /></div>
          {(filters.action || filters.entity || filters.from_date || filters.to_date || filters.user_id) && (
            <button className="btn btn-outline btn-sm" onClick={() => setFilters(EMPTY_FILTERS)}>Clear</button>
          )}
        </div>
      </Card>

      <div style={{ marginTop: 16 }}>
        <Card title="Change log" subtitle={`${rows.length} most recent entries`}>
        <DataTable
          rows={rows}
          emptyText="No audit entries yet — changes made from now on will appear here."
          columns={[
            { label: 'When', render: (row) => <span className="strong">{stamp(row.created_at)}</span> },
            {
              label: 'Changed by',
              render: (row) => (
                <span>
                  {row.full_name || row.username || 'System'}
                  {row.username && <span className="muted"> · {row.username}</span>}
                </span>
              ),
            },
            { label: 'Action', render: (row) => <span className="mono">{row.action}</span> },
            { label: 'Module', render: (row) => <span>{row.entity || '—'}{row.entity_id ? ` #${row.entity_id}` : ''}</span> },
            {
              label: 'Details',
              render: (row) => (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className="muted" style={{ fontSize: 11 }}>{bodySummary(row.details)}</span>
                  <button className="btn btn-outline btn-sm" onClick={() => setSelected(row)}><Search size={13} /> View</button>
                </div>
              ),
            },
          ]}
        />
        </Card>
      </div>

      <Modal open={!!selected} onClose={() => setSelected(null)} title={selected ? `${selected.action} · ${stamp(selected.created_at)}` : ''} width={820}>
        {selected && (
          <div style={{ maxHeight: 520, overflow: 'auto' }}>
            <Field label="Changed by" full>
              <input readOnly value={selected.full_name || selected.username || 'System'} />
            </Field>
            <Field label="Change details" full>
              <pre className="mono" style={{ background: '#f8fafc', padding: 12, borderRadius: 8, fontSize: 11, whiteSpace: 'pre-wrap' }}>
                {JSON.stringify(selected.details, null, 2)}
              </pre>
            </Field>
          </div>
        )}
      </Modal>
    </>
  )
}
