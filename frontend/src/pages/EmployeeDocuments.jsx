import { useEffect, useMemo, useRef, useState } from 'react'
import { Download, Eye, FileImage, FileText, LayoutGrid, List, Trash2, Upload } from 'lucide-react'
import api, { errorMessage } from '../api'
import { useAuth } from '../context/AuthContext'
import { DOCUMENT_SIZE_MB, prepareDocument } from '../utils/documentUpload'
import {
  Badge, Card, DataTable, Field, Modal, Notice, PageHead, SearchableSelect, fmtDate,
} from '../components/ui'

const ALL_CATEGORIES = [
  { value: 'appointment_order', label: 'Appointment order' },
  { value: 'medical_fitness', label: 'Medical fitness certificate' },
  { value: 'antecedent_verification', label: 'Antecedent verification form (HR only)' },
  { value: 'employee_pan', label: 'Employee PAN card' },
  { value: 'employee_aadhaar', label: 'Employee Aadhaar card' },
  { value: 'nominee_pan', label: 'Nominee PAN card' },
  { value: 'nominee_aadhaar', label: 'Nominee Aadhaar card' },
]
const KYC_VALUES = ['employee_pan', 'employee_aadhaar', 'nominee_pan', 'nominee_aadhaar']
const EMPLOYEE_CATEGORIES = ALL_CATEGORIES.filter((c) => KYC_VALUES.includes(c.value))
const REQUIRED_DOCUMENTS = [
  { value: 'appointment_order', label: 'Appointment order' },
  { value: 'medical_fitness', label: 'Medical fitness' },
  { value: 'employee_pan', label: 'Employee PAN' },
  { value: 'employee_aadhaar', label: 'Employee Aadhaar' },
  { value: 'nominee_pan', label: 'Nominee PAN' },
  { value: 'nominee_aadhaar', label: 'Nominee Aadhaar' },
  { value: 'antecedent_verification', label: 'Antecedent verification' },
]
const ROSTER_STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'complete', label: 'Complete' },
  { value: 'pending', label: 'Pending' },
]
const IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png']

function isImage(row) {
  const ext = (row?.original_filename || '').split('.').pop()?.toLowerCase()
  return IMAGE_EXTENSIONS.includes(ext) || String(row?.content_type || '').startsWith('image/')
}

function isPdf(row) {
  const ext = (row?.original_filename || '').split('.').pop()?.toLowerCase()
  return ext === 'pdf' || row?.content_type === 'application/pdf'
}

export default function EmployeeDocuments() {
  const { user, has } = useAuth()
  const isHR = (user?.roles || []).some((role) =>
    ['HR Manager', 'Admin'].includes(role?.name)) || user?.username === 'admin'
  const canManage = isHR && has('document.manage')
  const canSelfUpload = !isHR && Boolean(user?.employee_id)
    && has('document.view') && has('self.portal')
  const canUpload = canManage || canSelfUpload

  const [rows, setRows] = useState([])
  const [employees, setEmployees] = useState([])
  const [selfEmployee, setSelfEmployee] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [rosterSearch, setRosterSearch] = useState('')
  const [rosterStatus, setRosterStatus] = useState('')
  const [view, setView] = useState('tiles')
  const [modal, setModal] = useState(false)
  const [form, setForm] = useState({ employee_id: '', category: 'employee_pan' })
  const [preview, setPreview] = useState(null)
  const [previewUrl, setPreviewUrl] = useState('')
  const [previewLoading, setPreviewLoading] = useState(false)
  const fileRef = useRef(null)

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const response = await api.get('/employee-documents')
      setRows(response.data)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  useEffect(() => {
    if (!isHR) {
      if (user?.employee_id) {
        api.get('/employees/me')
          .then((r) => setSelfEmployee(r.data))
          .catch(() => {})
      }
      return undefined
    }

    let active = true
    const loadEmployees = async () => {
      const all = []
      let skip = 0
      let total = 0
      for (;;) {
        const response = await api.get('/employees', { params: { skip, limit: 500 } })
        const items = response.data.items || []
        total = response.data.total || 0
        all.push(...items)
        skip += items.length
        if (!items.length || skip >= total) break
      }
      if (active) setEmployees(all)
    }
    loadEmployees().catch(() => {})
    return () => { active = false }
  }, [isHR, user?.employee_id])

  useEffect(() => {
    if (!preview) return undefined
    let active = true
    setPreviewUrl('')
    setPreviewLoading(true)
    api.get(`/employee-documents/${preview.id}/download`, { responseType: 'blob' })
      .then((response) => {
        if (active) {
          const blob = new Blob([response.data], { type: response.data.type || preview.content_type || '' })
          setPreviewUrl(URL.createObjectURL(blob))
        }
      })
      .catch((err) => {
        if (active) { setError(errorMessage(err)); setPreview(null) }
      })
      .finally(() => { if (active) setPreviewLoading(false) })
    return () => { active = false }
  }, [preview?.id])

  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl) }, [previewUrl])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return rows.filter((row) => {
      if (category && row.category !== category) return false
      if (!q) return true
      return [row.employee_code, row.employee_name, row.original_filename, row.category_label]
        .some((value) => String(value || '').toLowerCase().includes(q))
    })
  }, [rows, search, category])

  const documentsByEmployee = useMemo(() => {
    const map = {}
    rows.forEach((row) => {
      if (!map[row.employee_id]) map[row.employee_id] = new Set()
      map[row.employee_id].add(row.category)
    })
    return map
  }, [rows])

  const roster = useMemo(() => employees.map((employee) => {
    const uploaded = documentsByEmployee[employee.id] || new Set()
    const missing = REQUIRED_DOCUMENTS.filter((doc) => !uploaded.has(doc.value))
    return {
      ...employee,
      uploaded_count: REQUIRED_DOCUMENTS.length - missing.length,
      missing_labels: missing.map((doc) => doc.label),
      complete: missing.length === 0,
    }
  }), [employees, documentsByEmployee])

  const filteredRoster = useMemo(() => {
    const q = rosterSearch.trim().toLowerCase()
    return roster.filter((row) => {
      if (rosterStatus === 'complete' && !row.complete) return false
      if (rosterStatus === 'pending' && row.complete) return false
      if (!q) return true
      return [row.employee_code, row.full_name, row.first_name, row.last_name]
        .some((value) => String(value || '').toLowerCase().includes(q))
    })
  }, [roster, rosterSearch, rosterStatus])

  const completeCount = roster.filter((row) => row.complete).length

  const download = async (row) => {
    if (!row) return
    setError('')
    try {
      const response = await api.get(`/employee-documents/${row.id}/download`, { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.download = row.original_filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const closePreview = () => {
    setPreview(null)
    setPreviewUrl('')
  }

  const openPreview = (row) => {
    setError('')
    setPreview(row)
  }

  const canDelete = (row) => canManage || (
    canSelfUpload
    && row.employee_id === user?.employee_id
    && KYC_VALUES.includes(row.category)
    && row.uploaded_by === user?.id
  )

  const openUpload = () => {
    setForm({
      employee_id: canManage ? '' : String(user?.employee_id || ''),
      category: canManage ? 'appointment_order' : 'employee_pan',
    })
    setModal(true)
  }

  const openUploadFor = (employee) => {
    setForm({ employee_id: String(employee.id), category: 'appointment_order' })
    setError('')
    setModal(true)
  }

  const upload = async (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    const employeeId = canManage ? form.employee_id : user?.employee_id
    if (!employeeId || !form.category) {
      setError('Select an employee and document type first')
      return
    }
    setError('')
    setNotice('')
    let prepared
    try {
      prepared = await prepareDocument(file)
    } catch (err) {
      setError(err.message || errorMessage(err))
      return
    }
    const body = new FormData()
    body.append('employee_id', String(employeeId))
    body.append('category', form.category)
    body.append('file', prepared)
    try {
      const response = await api.post('/employee-documents', body)
      setNotice(`${response.data.category_label} uploaded`)
      setModal(false)
      load()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const remove = async (row) => {
    if (!window.confirm(`Remove ${row.original_filename}?`)) return
    setError('')
    try {
      await api.delete(`/employee-documents/${row.id}`)
      setNotice('Document removed')
      if (preview?.id === row.id) closePreview()
      load()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const columns = [
    ...(isHR ? [{
      key: 'employee',
      label: 'Employee',
      render: (row) => (
        <><strong>{row.employee_code}</strong><div className="muted">{row.employee_name}</div></>
      ),
    }] : []),
    {
      key: 'category',
      label: 'Document',
      render: (row) => <Badge status={row.category === 'antecedent_verification' ? 'pending' : 'info'}>{row.category_label}</Badge>,
    },
    {
      key: 'file',
      label: 'File',
      render: (row) => (
        <><div>{row.original_filename}</div><div className="muted">{Math.ceil((row.size_bytes || 0) / 1024)} KB</div></>
      ),
    },
    {
      key: 'uploaded',
      label: 'Uploaded',
      render: (row) => (
        <>{fmtDate(row.uploaded_at)}<div className="muted">{row.uploaded_by_name || 'HR'}</div></>
      ),
    },
    {
      key: 'actions',
      label: 'Actions',
      className: 'text-right',
      render: (row) => (
        <span style={{ display: 'inline-flex', gap: 6 }}>
          <button className="btn btn-outline btn-sm" onClick={() => openPreview(row)}><Eye size={14} /> View</button>
          <button className="btn btn-outline btn-sm" onClick={() => download(row)}><Download size={14} /> Download</button>
          {canDelete(row) && <button className="btn btn-danger btn-sm btn-icon" onClick={() => remove(row)} title="Delete"><Trash2 size={14} /></button>}
        </span>
      ),
    },
  ]

  const visibleCategories = canManage
    ? ALL_CATEGORIES
    : ALL_CATEGORIES.filter((c) => c.value !== 'antecedent_verification')

  const rosterColumns = [
    {
      label: 'Employee',
      render: (row) => (
        <><strong>{row.employee_code}</strong><div className="muted">{row.full_name || `${row.first_name} ${row.last_name}`.trim()}</div></>
      ),
    },
    {
      label: 'Uploaded',
      render: (row) => <><span className="strong">{row.uploaded_count}/{REQUIRED_DOCUMENTS.length}</span><div className="muted">document types</div></>,
    },
    {
      label: 'Status',
      render: (row) => <Badge status={row.complete ? 'active' : 'pending'}>{row.complete ? 'Complete' : 'Pending'}</Badge>,
    },
    {
      label: 'Missing documents',
      render: (row) => row.complete
        ? <span className="muted">—</span>
        : <div>{row.missing_labels.map((label) => <span className="chip" key={label}>{label}</span>)}</div>,
    },
    {
      label: 'Actions',
      className: 'text-right',
      render: (row) => (
        <span style={{ display: 'inline-flex', gap: 6 }}>
          <button className="btn btn-outline btn-sm" onClick={() => { setSearch(row.employee_code); setCategory('') }}>
            <Eye size={14} /> View files
          </button>
          {canManage && (
            <button className="btn btn-primary btn-sm" onClick={() => openUploadFor(row)}>
              <Upload size={14} /> Upload
            </button>
          )}
        </span>
      ),
    },
  ]

  return (
    <>
      <PageHead
        title="Employee documents"
        subtitle={isHR ? 'Employee-wise document status and all uploaded files' : 'Your KYC uploads and HR documents, all in one place'}
        actions={canUpload && (
          <button className="btn btn-primary" onClick={openUpload}>
            <Upload size={15} /> Upload document
          </button>
        )}
      />
      <Notice type="error">{error}</Notice>
      <Notice type="success">{notice}</Notice>

      {isHR && (
        <div style={{ marginBottom: 16 }}>
          <Card
            title={`Employee document status (${completeCount}/${roster.length} complete)`}
            subtitle="Checklist covers all 7 document types, including the HR-only antecedent verification form"
          >
            <div className="toolbar">
              <input value={rosterSearch} onChange={(e) => setRosterSearch(e.target.value)} placeholder="Search employee name or code…" style={{ width: 260 }} />
              <SearchableSelect
                value={rosterStatus}
                onChange={setRosterStatus}
                options={ROSTER_STATUS_OPTIONS}
                placeholder="All statuses"
                style={{ width: 200 }}
              />
            </div>
            <DataTable
              columns={rosterColumns}
              rows={filteredRoster}
              loading={loading}
              emptyText="No employees match your filters"
            />
          </Card>
        </div>
      )}

      <Card>
        <div className="toolbar">
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search employee or file…" style={{ width: 260 }} />
          <SearchableSelect
            value={category}
            onChange={setCategory}
            options={[{ value: '', label: 'All document types' }, ...visibleCategories]}
            placeholder="All document types"
            style={{ width: 260 }}
          />
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
            <button className={`btn btn-sm ${view === 'tiles' ? 'btn-primary' : 'btn-outline'}`} onClick={() => setView('tiles')}><LayoutGrid size={14} /> Tiles</button>
            <button className={`btn btn-sm ${view === 'list' ? 'btn-primary' : 'btn-outline'}`} onClick={() => setView('list')}><List size={14} /> List</button>
          </div>
        </div>

        {view === 'tiles' ? (
          filtered.length ? (
            <div className="doc-tiles">
              {filtered.map((row) => (
                <div className="doc-tile" key={row.id}>
                  <button className="doc-tile-preview" onClick={() => openPreview(row)} title={`Preview ${row.original_filename}`}>
                    {isImage(row) ? <FileImage size={38} /> : <FileText size={38} />}
                  </button>
                  <div className="doc-tile-body" onClick={() => openPreview(row)} style={{ cursor: 'pointer' }}>
                    <span className="chip">{row.category_label}</span>
                    <div className="doc-tile-name">{row.original_filename}</div>
                    {isHR && <div className="doc-tile-meta">{row.employee_code} — {row.employee_name}</div>}
                    <div className="doc-tile-meta">{Math.ceil((row.size_bytes || 0) / 1024)} KB · {fmtDate(row.uploaded_at)}</div>
                    <div className="doc-tile-meta">Uploaded by {row.uploaded_by_name || 'HR'}</div>
                  </div>
                  <div className="doc-tile-actions">
                    <button className="btn btn-outline btn-sm" onClick={() => openPreview(row)}><Eye size={14} /> View</button>
                    <button className="btn btn-outline btn-sm" onClick={() => download(row)}><Download size={14} /></button>
                    {canDelete(row) && <button className="btn btn-danger btn-sm btn-icon" onClick={() => remove(row)} title="Delete"><Trash2 size={14} /></button>}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="muted" style={{ padding: '28px 0', textAlign: 'center' }}>
              {loading ? 'Loading documents…' : isHR ? 'No documents match your filters' : 'No documents uploaded yet — use Upload document to add your PAN / Aadhaar cards.'}
            </div>
          )
        ) : (
          <DataTable
            columns={columns}
            rows={filtered}
            loading={loading}
            emptyText={isHR ? 'No documents uploaded yet' : 'No documents available for your profile'}
          />
        )}
        <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>
          Employees can upload their own PAN and Aadhaar cards here or in My portal. HR uploads (appointment order, medical fitness) appear in the same tile view; antecedent verification forms remain HR-only.
        </p>
      </Card>

      <Modal
        open={modal}
        onClose={() => setModal(false)}
        title="Upload employee document"
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setModal(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={() => fileRef.current?.click()}><Upload size={15} /> Choose file</button>
          </>
        }
      >
        <div className="form-grid">
          {canManage ? (
            <Field label="Employee" full>
              <SearchableSelect
                value={form.employee_id}
                onChange={(value) => setForm({ ...form, employee_id: value })}
                options={employees.map((e) => ({
                  value: e.id,
                  label: `${e.employee_code} — ${e.full_name || `${e.first_name} ${e.last_name}`.trim()}`,
                }))}
                placeholder="Search employee…"
                clearable={false}
              />
            </Field>
          ) : (
            <Field label="Uploading for" full>
              <div className="strong" style={{ paddingTop: 8 }}>
                {selfEmployee?.employee_code ? `${selfEmployee.employee_code} — ${selfEmployee.full_name}` : user?.full_name || 'You'}
              </div>
            </Field>
          )}
          <Field label="Document type" full>
            <SearchableSelect
              value={form.category}
              onChange={(value) => setForm({ ...form, category: value })}
              options={canManage ? ALL_CATEGORIES : EMPLOYEE_CATEGORIES}
              placeholder="Select document type"
              clearable={false}
            />
          </Field>
        </div>
        <input
          ref={fileRef}
          type="file"
          hidden
          accept=".pdf,.doc,.docx,.jpg,.jpeg,.png"
          onChange={upload}
        />
        <p className="muted" style={{ fontSize: 12 }}>
          Maximum {DOCUMENT_SIZE_MB} MB per file. Oversized images are compressed automatically; please compress PDF or Word files before uploading. Uploading another file of the same type keeps both versions; the newest appears first.
        </p>
      </Modal>

      <Modal
        open={!!preview}
        onClose={closePreview}
        title={preview?.original_filename || 'Document preview'}
        width={900}
        footer={
          <>
            <button className="btn btn-outline" onClick={() => download(preview)}><Download size={15} /> Download</button>
            <button className="btn btn-outline" onClick={closePreview}>Close</button>
          </>
        }
      >
        {previewLoading ? <div className="loader">Loading preview…</div> : (
          previewUrl && isImage(preview) ? (
            <img src={previewUrl} alt={preview.original_filename} style={{ display: 'block', maxWidth: '100%', maxHeight: '62vh', margin: '0 auto' }} />
          ) : previewUrl && isPdf(preview) ? (
            <iframe src={previewUrl} title={preview.original_filename} style={{ width: '100%', height: '62vh', border: '1px solid var(--slate-200)' }} />
          ) : (
            <div className="muted">Preview is not available for this file type. Download it to view.</div>
          )
        )}
      </Modal>
    </>
  )
}
