import { useEffect, useRef, useState } from 'react'
import { Calculator, CheckCircle2, Download, FileSpreadsheet, Plus, Upload, Wallet } from 'lucide-react'
import api, { errorMessage } from '../api'
import { useAuth } from '../context/AuthContext'
import { Badge, Card, DataTable, Field, Modal, Notice, PageHead, SearchableSelect, Stat } from '../components/ui'

const MONTH_OPTIONS = Array.from({ length: 12 }, (_, i) => ({
  value: i + 1, label: new Date(2020, i, 1).toLocaleString('en', { month: 'long' }),
}))

const EMPTY_STRUCTURE = {
  employee_id: '', effective_from: new Date().toISOString().slice(0, 10), basic: 0, hra: 0,
  special_allowance: 0, conveyance: 0, other_earnings: [], provident_fund: 0,
  esi: 0, professional_tax: 0, income_tax: 0, other_deductions: [],
}

const money = (value) => `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

export default function Payroll() {
  const { has } = useAuth()
  const selfService = has('payslip.view') && !has('payroll.view')
  const [tab, setTab] = useState(selfService ? 'slips' : 'periods')
  const [periods, setPeriods] = useState([])
  const [structures, setStructures] = useState([])
  const [payslips, setPayslips] = useState([])
  const [employees, setEmployees] = useState([])
  const [selectedPeriod, setSelectedPeriod] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [periodModal, setPeriodModal] = useState(false)
  const [newPeriod, setNewPeriod] = useState({ month: new Date().getMonth() + 1, year: new Date().getFullYear() })
  const [structureModal, setStructureModal] = useState(false)
  const [structure, setStructure] = useState(EMPTY_STRUCTURE)
  const [editingStructure, setEditingStructure] = useState(null)
  const [importing, setImporting] = useState(false)
  const [replaceExisting, setReplaceExisting] = useState(false)
  const fileRef = useRef(null)
  const [downloadModal, setDownloadModal] = useState(false)
  const [downloadPeriods, setDownloadPeriods] = useState([])
  const [includeDemo, setIncludeDemo] = useState(false)
  const [downloading, setDownloading] = useState(false)

  const load = () => {
    api.get('/payroll/periods').then((r) => setPeriods(r.data)).catch((e) => setError(errorMessage(e)))
    if (!selfService) {
      api.get('/payroll/structures').then((r) => setStructures(r.data)).catch(() => {})
      api.get('/employees?limit=500').then((r) => setEmployees(r.data.items)).catch(() => {})
    }
    api.get(`/payroll/payslips${selectedPeriod ? `?period_id=${selectedPeriod}` : ''}`).then((r) => setPayslips(r.data)).catch(() => {})
  }
  useEffect(() => { load() }, [selectedPeriod, selfService])
  useEffect(() => { if (selfService) setTab('slips') }, [selfService])

  const createPeriod = async () => {
    try {
      await api.post('/payroll/periods/from-month', null, { params: newPeriod })
      setPeriodModal(false); setNotice('Payroll period created'); load()
    } catch (err) { setError(errorMessage(err)) }
  }

  const process = async (period) => {
    setBusy(true); setError(''); setNotice('')
    try {
      const r = await api.post('/payroll/process', {
        period_id: period.id, scope: 'device', replace_existing: true,
      })
      setNotice(
        `${r.data.processed} live salary slips generated for ${r.data.period}` +
        (r.data.removed_existing ? ` · ${r.data.removed_existing} demo slip(s) removed` : '')
      ); load()
    } catch (err) { setError(errorMessage(err)) } finally { setBusy(false) }
  }

  const markPaid = async (slip) => {
    try { await api.post(`/payroll/payslips/${slip.id}/mark-paid`); setNotice('Marked as paid'); load() }
    catch (err) { setError(errorMessage(err)) }
  }

  const download = async (slip) => {
    try {
      const res = await api.get(`/payroll/payslips/${slip.id}/pdf`, { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }))
      const link = document.createElement('a')
      link.href = url
      link.download = `payslip_${slip.employee_code}_${slip.period_name}.pdf`
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) { setError(errorMessage(err)) }
  }

  const openStructure = (row) => {
    setEditingStructure(row?.id || null)
    setStructure(row ? { ...EMPTY_STRUCTURE, ...row } : EMPTY_STRUCTURE)
    setStructureModal(true)
  }

  const saveStructure = async () => {
    try {
      const payload = { ...structure }
      if (editingStructure) await api.put(`/payroll/structures/${editingStructure}`, payload)
      else await api.post('/payroll/structures', payload)
      setStructureModal(false); setNotice('Salary structure saved'); load()
    } catch (err) { setError(errorMessage(err)) }
  }

  const downloadSalaryFile = async (url, filename) => {
    try {
      const res = await api.get(url, { responseType: 'blob' })
      const href = URL.createObjectURL(new Blob([res.data]))
      const link = document.createElement('a')
      link.href = href
      link.download = filename
      link.click()
      URL.revokeObjectURL(href)
    } catch (err) { setError(errorMessage(err)) }
  }

  const importStructures = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    setImporting(true); setError(''); setNotice('')
    try {
      const body = new FormData()
      body.append('file', file)
      body.append('replace_existing', String(replaceExisting))
      const res = await api.post('/payroll/structures/import', body)
      const result = res.data
      const summary = `${result.created} created, ${result.updated} updated` +
        (result.removed ? `, ${result.removed} existing removed` : '')
      setNotice(`Salary structures imported — ${summary}`)
      if (result.errors?.length) {
        setError(`${result.errors.length} row(s) skipped: ${result.errors.slice(0, 4).join(' | ')}`)
      }
      load()
    } catch (err) { setError(errorMessage(err)) }
    finally {
      setImporting(false)
      event.target.value = ''
    }
  }

  const openDownloadModal = () => {
    setDownloadPeriods(selectedPeriod ? [selectedPeriod] : periods.map((p) => p.id))
    setDownloadModal(true)
  }

  const downloadMultiple = async () => {
    setDownloading(true); setError(''); setNotice('')
    try {
      const res = await api.post('/payroll/payslips/download-zip', {
        period_ids: downloadPeriods,
        include_demo: includeDemo,
      }, { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([res.data], { type: 'application/zip' }))
      const link = document.createElement('a')
      link.href = url
      link.download = 'salary_slips_multiple_months.zip'
      link.click()
      URL.revokeObjectURL(url)
      setDownloadModal(false)
      setNotice('Salary slips ZIP downloaded')
    } catch (err) { setError(errorMessage(err)) } finally { setDownloading(false) }
  }

  const totalNet = payslips.reduce((sum, p) => sum + (p.net_salary || 0), 0)

  return (
    <>
      <PageHead
        title={selfService ? 'My salary slips' : 'Payroll'}
        subtitle={selfService ? 'View and download your salary slips' : 'Salary structures, monthly processing and salary slips'}
        actions={selfService ? (
          <button className="btn btn-primary" onClick={openDownloadModal}><Download size={15} /> Download slips</button>
        ) : (
          <button className="btn btn-primary" onClick={() => setPeriodModal(true)}><Plus size={15} /> New period</button>
        )}
      />
      <Notice type="error">{error}</Notice><Notice type="success">{notice}</Notice>
      {!selfService && <Notice type="info">
        Payroll now processes <strong>live biometric employees</strong> (<code>DEV-*</code>) using their device attendance.
        Import salary structures before processing — demo <code>EMP-*</code> slips are removed automatically.
      </Notice>}
      <div className="tabs">
        {!selfService && <button className={`tab ${tab === 'periods' ? 'active' : ''}`} onClick={() => setTab('periods')}>Payroll periods</button>}
        {!selfService && <button className={`tab ${tab === 'structures' ? 'active' : ''}`} onClick={() => setTab('structures')}>Salary structures</button>}
        <button className={`tab ${tab === 'slips' ? 'active' : ''}`} onClick={() => setTab('slips')}>{selfService ? 'Salary slips' : 'Salary slips'}</button>
      </div>

      {tab === 'periods' && (
        <Card title="Payroll periods">
          <DataTable rows={periods} emptyText="No payroll periods yet" columns={[
            { label: 'Period', render: (r) => <><span className="strong">{r.name}</span><span className="sub">{r.start_date} → {r.end_date}</span></> },
            { label: 'Status', render: (r) => <Badge status={r.status} /> },
            { label: 'Slips', render: (r) => <button className="btn btn-outline btn-sm" onClick={() => { setSelectedPeriod(r.id); setTab('slips') }}>View slips</button> },
            { label: 'Actions', className: 'text-right', render: (r) => <div className="row-actions" style={{ justifyContent: 'flex-end' }}>
              <button className="btn btn-primary btn-sm" disabled={busy || r.status === 'paid'} onClick={() => process(r)}><Calculator size={14} /> {r.status === 'draft' ? 'Process' : 'Reprocess'}</button>
            </div> },
          ]} />
        </Card>
      )}

      {tab === 'structures' && (
        <Card title={`Salary structures (${structures.length})`} actions={<button className="btn btn-primary btn-sm" onClick={() => openStructure(null)}><Plus size={14} /> Add structure</button>}>
          <div className="toolbar" style={{ justifyContent: 'space-between' }}>
            <div className="toolbar" style={{ marginBottom: 0 }}>
              <button className="btn btn-outline btn-sm" disabled={importing} onClick={() => fileRef.current?.click()}>
                <Upload size={14} /> {importing ? 'Importing…' : 'Import CSV / XLSX'}
              </button>
              <button className="btn btn-outline btn-sm" onClick={() => downloadSalaryFile('/payroll/structures/export?format=xlsx', 'salary_structures.xlsx')}>
                <Download size={14} /> Export
              </button>
              <button className="btn btn-outline btn-sm" onClick={() => downloadSalaryFile('/payroll/structures/template?format=xlsx', 'salary_structures_template.xlsx')}>
                <FileSpreadsheet size={14} /> Template
              </button>
              <label className="field-inline" style={{ cursor: 'pointer' }}>
                <input type="checkbox" checked={replaceExisting} onChange={(e) => setReplaceExisting(e.target.checked)} />
                Replace existing live structures
              </label>
            </div>
            <span className="sub">CSV or XLSX · matched by Employee Code / device ID</span>
          </div>
          <input ref={fileRef} type="file" accept=".csv,.xlsx,.xlsm" style={{ display: 'none' }} onChange={importStructures} />
          <Notice type="info">
            Download the <strong>template</strong> to see the accepted columns. <code>Employee Code</code> can be
            <code> DEV-111</code> or just <code>111</code>. Import updates the matching effective date, or creates a new row.
            Enable <strong>Replace existing live structures</strong> to clear all live rows before importing.
          </Notice>
          <DataTable rows={structures} emptyText="No live salary structures — import salary data or use the template" columns={[
            { label: 'Employee', render: (r) => <><span className="strong">{r.employee_name}</span><span className="sub">{r.employee_code}</span></> },
            { label: 'Effective from', render: (r) => r.effective_from || '—' },
            { label: 'Basic', render: (r) => money(r.basic) },
            { label: 'HRA', render: (r) => money(r.hra) },
            { label: 'Allowances', render: (r) => money((r.special_allowance || 0) + (r.conveyance || 0)) },
            { label: 'Gross', render: (r) => money((r.basic || 0) + (r.hra || 0) + (r.special_allowance || 0) + (r.conveyance || 0)) },
            { label: 'Actions', className: 'text-right', render: (r) => <button className="btn btn-outline btn-sm" onClick={() => openStructure(r)}>Edit</button> },
          ]} />
        </Card>
      )}

      {tab === 'slips' && (
        <>
          <div className="toolbar">
            <div className="field-inline"><label>Payroll period</label>
              <SearchableSelect value={selectedPeriod} onChange={setSelectedPeriod} options={periods.map((p) => ({ value: p.id, label: p.name }))} placeholder="All periods" style={{ width: 220 }} />
            </div>
            <button className="btn btn-outline btn-sm" onClick={openDownloadModal}><Download size={14} /> Download multiple months</button>
          </div>
          <div className={`grid grid-${selfService ? 2 : 3}`} style={{ marginBottom: 16 }}>
            <Stat icon={<Wallet size={19} />} label="Salary slips" value={payslips.length} />
            <Stat icon={<Wallet size={19} />} label={selfService ? 'Total net pay' : 'Total net pay'} value={money(totalNet)} color="#16a34a" />
            {!selfService && <Stat icon={<CheckCircle2 size={19} />} label="Marked paid" value={payslips.filter((p) => p.status === 'paid').length} color="#0284c7" />}
          </div>
          <Card title={selfService ? 'My salary slips' : 'Generated salary slips'}>
            <DataTable rows={payslips} emptyText={selfService ? 'No salary slips available' : 'Process a payroll period to generate live slips'} columns={[
              { label: 'Employee', render: (r) => <><span className="strong">{r.employee_name}</span><span className="sub">{r.employee_code}</span></> },
              { label: 'Paid days', render: (r) => <span className="mono">{r.paid_days} / {r.working_days}</span> },
              { label: 'Gross', render: (r) => <span className="mono">{money(r.gross_salary)}</span> },
              { label: 'Deductions', render: (r) => <span className="mono">{money(r.total_deductions)}</span> },
              { label: 'Net pay', render: (r) => <span className="strong mono">{money(r.net_salary)}</span> },
              { label: 'Status', render: (r) => <Badge status={r.status} /> },
              { label: 'Actions', className: 'text-right', render: (r) => <div className="row-actions" style={{ justifyContent: 'flex-end' }}>
                <button className="btn btn-outline btn-sm" onClick={() => download(r)}><Download size={14} /> PDF</button>
                {!selfService && r.status !== 'paid' && <button className="btn btn-success btn-sm" onClick={() => markPaid(r)}>Mark paid</button>}
              </div> },
            ]} />
          </Card>
        </>
      )}

      {!selfService && <Modal open={periodModal} onClose={() => setPeriodModal(false)} title="Create payroll period"
        footer={<><button className="btn btn-outline" onClick={() => setPeriodModal(false)}>Cancel</button><button className="btn btn-primary" onClick={createPeriod}>Create period</button></>}>
        <div className="form-grid">
          <Field label="Month"><SearchableSelect value={newPeriod.month} onChange={(v) => setNewPeriod({ ...newPeriod, month: v })} options={MONTH_OPTIONS} clearable={false} /></Field>
          <Field label="Year"><input type="number" value={newPeriod.year} onChange={(e) => setNewPeriod({ ...newPeriod, year: +e.target.value })} /></Field>
        </div>
      </Modal>}

      {!selfService && <Modal open={structureModal} onClose={() => setStructureModal(false)} title={editingStructure ? 'Edit salary structure' : 'Add salary structure'} width={720}
        footer={<><button className="btn btn-outline" onClick={() => setStructureModal(false)}>Cancel</button><button className="btn btn-primary" onClick={saveStructure}>Save structure</button></>}>
        <div className="form-grid">
          <Field label="Employee" full><SearchableSelect value={structure.employee_id} onChange={(v) => setStructure({ ...structure, employee_id: v })} options={employees.map((e) => ({ value: e.id, label: `${e.employee_code} — ${e.full_name || `${e.first_name} ${e.last_name}`}` }))} placeholder="Select employee" disabled={!!editingStructure} /></Field>
          <Field label="Effective from"><input type="date" value={structure.effective_from || ''} onChange={(e) => setStructure({ ...structure, effective_from: e.target.value })} /></Field>
          <div />
          {[
            ['basic', 'Basic salary'], ['hra', 'House rent allowance'], ['special_allowance', 'Special allowance'],
            ['conveyance', 'Conveyance'], ['provident_fund', 'Provident fund'], ['esi', 'ESI'],
            ['professional_tax', 'Professional tax'], ['income_tax', 'Income tax'],
          ].map(([key, label]) => <Field key={key} label={label}><input type="number" step="0.01" value={structure[key] || 0} onChange={(e) => setStructure({ ...structure, [key]: +e.target.value })} /></Field>)}
        </div>
      </Modal>}

      <Modal open={downloadModal} onClose={() => setDownloadModal(false)} title="Download salary slips"
        footer={<>
          <button className="btn btn-outline" onClick={() => setDownloadModal(false)}>Cancel</button>
          <button className="btn btn-primary" disabled={downloading} onClick={downloadMultiple}>
            {downloading ? 'Preparing ZIP…' : 'Download ZIP'}
          </button>
        </>}>
        <Notice type="info">Select one or more payroll periods. Leave all unchecked to download every available month.</Notice>
        <div style={{ display: 'grid', gap: 8, maxHeight: 280, overflowY: 'auto' }}>
          {periods.map((p) => (
            <label key={p.id} className="field-inline" style={{ cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={downloadPeriods.includes(p.id)}
                onChange={(e) => setDownloadPeriods(
                  e.target.checked ? [...downloadPeriods, p.id] : downloadPeriods.filter((id) => id !== p.id),
                )}
              />
              {p.name}
            </label>
          ))}
          {!periods.length && <span className="sub">No payroll periods available yet.</span>}
        </div>
        {!selfService && <div style={{ marginTop: 14 }}>
          <label className="field-inline" style={{ cursor: 'pointer' }}>
            <input type="checkbox" checked={includeDemo} onChange={(e) => setIncludeDemo(e.target.checked)} />
            Include demo slips
          </label>
        </div>}
      </Modal>
    </>
  )
}
