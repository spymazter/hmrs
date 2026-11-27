import { useEffect, useState } from 'react'
import { CakeSlice, CalendarDays, Sparkles } from 'lucide-react'
import api, { errorMessage } from '../api'
import { Badge, Card, Notice, PageHead } from '../components/ui'

function label(iso) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    weekday: 'short', day: 'numeric', month: 'short',
  })
}

function Person({ person }) {
  return (
    <div className="birthday-person">
      <div className="birthday-avatar"><CakeSlice size={18} /></div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="birthday-name">{person.name}</div>
        <div className="muted" style={{ fontSize: 11 }}>
          {person.employee_code}
          {person.department ? ` · ${person.department}` : ''}
          {person.designation ? ` · ${person.designation}` : ''}
        </div>
      </div>
      <div style={{ textAlign: 'right' }}>
        <div className="strong" style={{ fontSize: 12 }}>{label(person.birthday)}</div>
        {person.days_away === 0
          ? <Badge status="approved">Today</Badge>
          : <Badge status="leave">In {person.days_away} day{person.days_away === 1 ? '' : 's'}</Badge>}
      </div>
    </div>
  )
}

function List({ period, emptyText }) {
  if (!period?.items?.length) {
    return <div className="birthday-empty">{emptyText}</div>
  }
  return <div className="birthday-list">{period.items.map((person) => (
    <Person key={`${person.employee_id}-${person.birthday}`} person={person} />
  ))}</div>
}

export default function Birthdays() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get('/employees/birthdays')
      .then((res) => setData(res.data))
      .catch((err) => setError(errorMessage(err)))
  }, [])

  return (
    <>
      <PageHead title="Happy Birthday" subtitle="Upcoming birthdays this week and this month" />
      <Notice type="error">{error}</Notice>

      {data?.today?.length > 0 && (
        <div className="birthday-hero">
          <Sparkles size={20} />
          <div>
            <strong>Happy birthday, {data.today.map((p) => p.name).join(', ')}!</strong>
            <div className="muted" style={{ fontSize: 12 }}>Celebrating today · {label(data.date)}</div>
          </div>
        </div>
      )}

      {!data ? <div className="loader">Loading birthdays…</div> : (
        <>
          <div className="grid grid-2">
            <Card
              title="This week"
              subtitle={`${label(data.week.start)} – ${label(data.week.end)} · ${data.week.items.length} upcoming`}
            >
              <List period={data.week} emptyText="No upcoming birthdays this week" />
            </Card>
            <Card
              title="This month"
              subtitle={`${label(data.month.start)} – ${label(data.month.end)} · ${data.month.items.length} upcoming`}
            >
              <List period={data.month} emptyText="No upcoming birthdays this month" />
            </Card>
          </div>
          <div className="birthday-note">
            <CalendarDays size={14} style={{ verticalAlign: -3, marginRight: 6 }} />
            Birthdays are read from employee date of birth. Add or update DOB in employee details to populate this portal.
          </div>
        </>
      )}
    </>
  )
}
