import React, { useEffect, useMemo, useState } from 'react'
import { api } from './api.js'

/* ============================ helpers ============================ */

const RECO = { ESCALATE: 'red', REQUEST_MORE_EVIDENCE: 'amber', MONITOR: 'green' }
const STATUS = { WATCH: 'blue', INVESTIGATING: 'amber', ESCALATE: 'red', RESOLVED: 'green' }
const RECO_RANK = { ESCALATE: 0, REQUEST_MORE_EVIDENCE: 1, MONITOR: 2, null: 3 }
const fmt = (n) => (n == null ? '—' : Number(n).toFixed(3))
const pct = (n) => (n == null ? '—' : `${Math.round(n * 100)}%`)

function Chip({ kind, children }) {
  return <span className={`chip ${kind || ''}`}>{children}</span>
}

function RecoCell({ inv }) {
  if (!inv) return <span className="sev none">NOT INVESTIGATED</span>
  return <span className={`sev ${inv.recommendation}`}>{inv.recommendation}</span>
}

function ErrorBox({ error }) {
  if (!error) return null
  return <div className="error-box">{error}</div>
}

/* ============================ shared data ============================ */

function useHealth() {
  const [health, setHealth] = useState(null)
  useEffect(() => { api.health().then(setHealth).catch(() => setHealth(null)) }, [])
  return health
}

function useMerchants() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => { api.merchants().then(setData).catch(e => setError(e.message)) }, [])
  return { data, error }
}

/**
 * Risk queue: every episode across merchants, joined with its latest
 * investigation. Built from /merchants + /merchants/{id}/episodes (the API
 * has no global queue endpoint; this is a client-side join, nothing cached
 * or invented).
 */
function useRiskQueue(merchantsData) {
  const [rows, setRows] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!merchantsData) return
    const withEpisodes = merchantsData.merchants.filter(m => m.episode_count > 0)
    Promise.all(withEpisodes.map(m => api.merchantEpisodes(m.merchant_id).catch(() => null)))
      .then(results => {
        const out = []
        results.forEach((r, i) => {
          if (!r) return
          r.episodes.forEach(ep => {
            const inv = (r.latest_investigations || {})[ep.episode_id] || null
            out.push({ merchant: withEpisodes[i], episode: ep, inv })
          })
        })
        out.sort((a, b) => {
          const ra = RECO_RANK[a.inv ? a.inv.recommendation : null] ?? 3
          const rb = RECO_RANK[b.inv ? b.inv.recommendation : null] ?? 3
          if (ra !== rb) return ra - rb
          const pa = a.inv && a.inv.approval_status === 'PENDING_HUMAN_REVIEW' ? 0 : 1
          const pb = b.inv && b.inv.approval_status === 'PENDING_HUMAN_REVIEW' ? 0 : 1
          if (pa !== pb) return pa - pb
          return (b.inv ? b.inv.hypotheses.RISK_DRIFT.support_score : b.episode.peak_score)
            - (a.inv ? a.inv.hypotheses.RISK_DRIFT.support_score : a.episode.peak_score)
        })
        setRows(out)
      })
      .catch(e => setError(e.message))
  }, [merchantsData])

  return { rows, error }
}

/* ============================ timeline chart ============================ */

function TimelineChart({ points, episode }) {
  if (!points || !points.length) return null
  const W = 920, H = 110, PAD = 6
  const d0 = Math.min(...points.map(p => p.day))
  const d1 = Math.max(...points.map(p => p.day))
  const x = day => PAD + ((day - d0) / (d1 - d0)) * (W - 2 * PAD)

  const series = [
    { key: 'txn_count', label: 'txn count', color: '#2b84eb' },
    { key: 'refund_rate', label: 'refund rate', color: '#b97a0a' },
    { key: 'dispute_rate', label: 'dispute rate', color: '#d93840' },
  ]
  const pathFor = (key) => {
    const vals = points.map(p => p[key])
    const lo = Math.min(...vals), hi = Math.max(...vals)
    const span = hi - lo || 1
    return points.map((p, i) => {
      const px = x(p.day)
      const py = H - PAD - ((p[key] - lo) / span) * (H - 2 * PAD)
      return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)},${py.toFixed(1)}`
    }).join(' ')
  }
  const driftDays = points.filter(p => p.predicted_drift_ms === 1).map(p => p.day)

  return (
    <div>
      <div className="timeline-wrap">
        <svg viewBox={`0 0 ${W} ${H}`}>
          {episode && (
            <rect x={x(episode.start_day)} y={0}
              width={Math.max(2, x(episode.current_day) - x(episode.start_day))} height={H}
              fill="rgba(217,56,64,0.07)" stroke="rgba(217,56,64,0.4)" strokeDasharray="4 3" />
          )}
          {series.map(s => <path key={s.key} d={pathFor(s.key)} fill="none" stroke={s.color} strokeWidth="1.3" />)}
          {driftDays.map(d => (
            <line key={d} x1={x(d)} y1={0} x2={x(d)} y2={H} stroke="#d93840" strokeWidth="0.8" opacity="0.5" />
          ))}
        </svg>
      </div>
      <div className="legend">
        {series.map(s => <span key={s.key} style={{ color: s.color }}>— {s.label}</span>)}
        <span style={{ color: '#d93840' }}>| flagged day</span>
        <span className="muted2">series individually normalized to range</span>
      </div>
    </div>
  )
}

function ConfidenceSpark({ history }) {
  if (!history || history.length < 2) return null
  const W = 150, H = 34, PAD = 3
  const scores = history.map(h => h[1])
  const lo = Math.min(...scores, 0), hi = Math.max(...scores, 1)
  const pts = history.map((h, i) => {
    const px = PAD + (i / (history.length - 1)) * (W - 2 * PAD)
    const py = H - PAD - ((h[1] - lo) / (hi - lo || 1)) * (H - 2 * PAD)
    return `${px.toFixed(1)},${py.toFixed(1)}`
  }).join(' ')
  return (
    <svg className="spark" width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
      <polyline points={pts} fill="none" stroke="#2b84eb" strokeWidth="1.3" />
      <line x1={0} y1={H - PAD - (0.62 - lo) / (hi - lo || 1) * (H - 2 * PAD)} x2={W}
        y2={H - PAD - (0.62 - lo) / (hi - lo || 1) * (H - 2 * PAD)} stroke="#c8d3e2" strokeDasharray="3 3" strokeWidth="0.8" />
    </svg>
  )
}

/* ============================ dashboard / queue ============================ */

function KpiRow({ summary }) {
  return (
    <div className="kpi-row">
      <div className="kpi"><div className="v mono">{summary.merchants_monitored}</div><div className="l">Merchants monitored</div></div>
      <div className="kpi"><div className="v mono">{summary.episodes_detected}</div><div className="l">Risk episodes</div></div>
      <div className="kpi"><div className="v mono">{summary.investigations_run}</div><div className="l">Investigations run</div></div>
      <div className="kpi"><div className="v mono alert">{summary.pending_human_review}</div><div className="l">Awaiting review</div></div>
      <div className="kpi"><div className="v mono">{summary.approved} <span className="muted2">/</span> {summary.overridden}</div><div className="l">Approved / overridden</div></div>
    </div>
  )
}

function QueueTable({ rows, openEpisode, limit }) {
  const shown = limit ? rows.slice(0, limit) : rows
  return (
    <table className="grid">
      <thead>
        <tr>
          <th>Severity</th><th>Merchant</th><th>Episode</th><th>Trigger signals</th>
          <th className="num">Risk score</th><th className="num">Age</th><th>Episode state</th>
          <th>Recommended action</th><th>Review</th><th></th>
        </tr>
      </thead>
      <tbody>
        {shown.map(({ merchant, episode, inv }) => {
          const score = inv ? inv.hypotheses.RISK_DRIFT.support_score : episode.peak_score
          const pending = inv && inv.approval_status === 'PENDING_HUMAN_REVIEW'
          return (
            <tr key={episode.episode_id} className="clickable"
              onClick={() => openEpisode(episode.episode_id, merchant.merchant_id)}>
              <td><RecoCell inv={inv} /></td>
              <td className="mono">{merchant.merchant_id}</td>
              <td className="mono">{episode.episode_id}</td>
              <td>{episode.signal_groups.map(g => <Chip key={g}>{g}</Chip>)}</td>
              <td className="num mono">{fmt(score)}</td>
              <td className="num mono">{episode.current_day - episode.start_day}d</td>
              <td><Chip kind={STATUS[episode.status]}>{episode.status}</Chip></td>
              <td>{inv ? inv.recommendation : <span className="muted2">—</span>}</td>
              <td>{inv
                ? <Chip kind={pending ? 'amber' : inv.approval_status === 'APPROVED' ? 'green' : 'purple'}>
                    {pending ? 'PENDING' : inv.approval_status}
                  </Chip>
                : <Chip kind="dim">NONE</Chip>}</td>
              <td><button className="link">open</button></td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function QueueEmptyState({ rows }) {
  if (rows) return <p className="muted" style={{ padding: 12 }}>No risk episodes detected across monitored merchants.</p>
  return <p className="muted" style={{ padding: 12 }}>Loading episode queue…</p>
}

function OverviewPage({ openMerchant, openEpisode, goto }) {
  const { data, error } = useMerchants()
  const { rows, error: qError } = useRiskQueue(data)

  return (
    <div>
      <div className="page-head">
        <h1>Risk Operations Overview</h1>
        <span className="desc">Post-onboarding merchant drift monitoring</span>
        <span className="refresh">all 240 observation days scored · engine deterministic</span>
      </div>
      <ErrorBox error={error || qError} />
      {data && <KpiRow summary={data.summary} />}

      <div className="panel">
        <div className="panel-head">
          <h2>Active risk queue</h2>
          <span className="hint">unreviewed escalations first, then by risk score</span>
          <div className="right"><button className="link" onClick={() => goto('queue')}>full queue</button></div>
        </div>
        <div className="panel-body tight">
          {rows && rows.length ? <QueueTable rows={rows} openEpisode={openEpisode} limit={8} /> : <QueueEmptyState rows={rows} />}
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Merchant monitoring</h2>
          <span className="hint">{data ? data.merchants.length : '…'} merchants · merchant-specific baselines</span>
        </div>
        <div className="panel-body tight">
          {data && (
            <table className="grid">
              <thead>
                <tr><th>Merchant</th><th>Category</th><th>Geography</th><th className="num">Days</th>
                  <th className="num">Episodes</th><th>Latest episode</th><th>State</th></tr>
              </thead>
              <tbody>
                {data.merchants.map(m => (
                  <tr key={m.merchant_id} className="clickable" onClick={() => openMerchant(m.merchant_id)}>
                    <td className="mono">{m.merchant_id}</td>
                    <td>{m.dominant_category}</td>
                    <td>{m.dominant_geo}</td>
                    <td className="num mono">{m.first_day}–{m.last_day}</td>
                    <td className="num mono">{m.episode_count}</td>
                    <td className="mono">{m.latest_episode_id || '—'}</td>
                    <td>{m.latest_episode_status
                      ? <Chip kind={STATUS[m.latest_episode_status]}>{m.latest_episode_status}</Chip>
                      : <Chip kind="dim">CLEAN</Chip>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

function QueuePage({ openEpisode }) {
  const { data, error } = useMerchants()
  const { rows, error: qError } = useRiskQueue(data)
  return (
    <div>
      <div className="page-head">
        <h1>Risk Queue</h1>
        <span className="desc">every detected episode with its latest investigation and review state</span>
      </div>
      <ErrorBox error={error || qError} />
      <div className="panel">
        <div className="panel-body tight">
          {rows && rows.length ? <QueueTable rows={rows} openEpisode={openEpisode} /> : <QueueEmptyState rows={rows} />}
        </div>
      </div>
    </div>
  )
}

function MerchantsPage({ openMerchant }) {
  const { data, error } = useMerchants()
  return (
    <div>
      <div className="page-head">
        <h1>Merchants</h1>
        <span className="desc">monitored population with per-merchant baselines</span>
      </div>
      <ErrorBox error={error} />
      <div className="panel">
        <div className="panel-body tight">
          {data && (
            <table className="grid">
              <thead>
                <tr><th>Merchant</th><th>Category</th><th>Geography</th><th className="num">Days</th>
                  <th className="num">Episodes</th><th>Latest episode</th><th>State</th></tr>
              </thead>
              <tbody>
                {data.merchants.map(m => (
                  <tr key={m.merchant_id} className="clickable" onClick={() => openMerchant(m.merchant_id)}>
                    <td className="mono">{m.merchant_id}</td>
                    <td>{m.dominant_category}</td>
                    <td>{m.dominant_geo}</td>
                    <td className="num mono">{m.first_day}–{m.last_day}</td>
                    <td className="num mono">{m.episode_count}</td>
                    <td className="mono">{m.latest_episode_id || '—'}</td>
                    <td>{m.latest_episode_status
                      ? <Chip kind={STATUS[m.latest_episode_status]}>{m.latest_episode_status}</Chip>
                      : <Chip kind="dim">CLEAN</Chip>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

/* ============================ merchant detail ============================ */

function MerchantPage({ merchantId, openEpisode, back }) {
  const [detail, setDetail] = useState(null)
  const [latest, setLatest] = useState({})
  const [error, setError] = useState(null)

  useEffect(() => {
    setDetail(null); setLatest({})
    api.merchant(merchantId).then(setDetail).catch(e => setError(e.message))
    api.merchantEpisodes(merchantId).then(r => setLatest(r.latest_investigations || {})).catch(() => { })
  }, [merchantId])

  if (error) return <ErrorBox error={error} />
  if (!detail) return <p className="muted">Loading merchant…</p>
  const flaggedDays = detail.behavioral_timeline.filter(p => p.predicted_drift_ms === 1).length
  const latestEp = detail.episodes[detail.episodes.length - 1]

  return (
    <div>
      <div className="page-head">
        <h1 className="mono">{detail.merchant_id}</h1>
        <span className="desc">{detail.dominant_category} · {detail.dominant_geo} · days {detail.first_day}–{detail.last_day}</span>
        <span className="refresh">
          {detail.episodes.length} episode(s) · {flaggedDays} flagged day(s)
          {latestEp && latestEp.status ? ` · latest ${latestEp.status}` : ' · no drift detected'}
        </span>
      </div>

      <div className="panel">
        <div className="panel-head"><h2>Behavioral timeline</h2>
          <span className="hint">observed values vs the merchant's own trailing baseline</span></div>
        <div className="panel-body">
          <TimelineChart points={detail.behavioral_timeline} episode={latestEp} />
        </div>
      </div>

      <div className="panel">
        <div className="panel-head"><h2>Baseline profile</h2>
          <span className="hint">observable aggregates only — no onboarding/KYC data exists in this dataset</span></div>
        <div className="panel-body tight">
          <table className="grid">
            <tbody>
              <tr><td className="muted">Dominant category</td><td>{detail.dominant_category}</td>
                <td className="muted">Dominant geography</td><td>{detail.dominant_geo}</td></tr>
              <tr><td className="muted">Observation window</td><td className="mono">day {detail.first_day} – {detail.last_day}</td>
                <td className="muted">Detector-flagged days</td><td className="mono">{flaggedDays} / {detail.behavioral_timeline.length}</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head"><h2>Episodes</h2>
          <span className="hint">grouped drift periods for this merchant</span></div>
        <div className="panel-body tight">
          {detail.episodes.length === 0
            ? <p className="muted" style={{ padding: 12 }}>No drift episodes detected for this merchant.</p>
            : (
              <table className="grid">
                <thead>
                  <tr><th>Episode</th><th>Window</th><th>Signals deviating</th>
                    <th className="num">Peak confidence</th><th>State</th>
                    <th>Latest recommendation</th><th>Review</th><th></th></tr>
                </thead>
                <tbody>
                  {detail.episodes.map(e => {
                    const inv = latest[e.episode_id]
                    return (
                      <tr key={e.episode_id} className="clickable" onClick={() => openEpisode(e.episode_id, merchantId)}>
                        <td className="mono">{e.episode_id}</td>
                        <td className="mono">{e.start_day}–{e.current_day}</td>
                        <td>{e.signal_groups.map(g => <Chip key={g}>{g}</Chip>)}</td>
                        <td className="num mono">{fmt(e.peak_score)}</td>
                        <td><Chip kind={STATUS[e.status]}>{e.status}</Chip></td>
                        <td>{inv ? inv.recommendation : <span className="muted2">not investigated</span>}</td>
                        <td>{inv
                          ? <Chip kind={inv.approval_status === 'PENDING_HUMAN_REVIEW' ? 'amber' : 'green'}>{inv.approval_status}</Chip>
                          : <Chip kind="dim">NONE</Chip>}</td>
                        <td><button className="link">open</button></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
        </div>
      </div>
    </div>
  )
}

/* ============================ episode / investigation ============================ */

const ACTOR = {
  human_decision: { label: 'Human', cls: 'human' },
  planner_decision: { label: 'Agent', cls: '' },
  tool_call: { label: 'Agent', cls: '' },
  hypothesis_update: { label: 'Agent', cls: '' },
  investigation_started: { label: 'System', cls: 'system' },
  loaded_episode_baseline_evidence: { label: 'System', cls: 'system' },
  recommendation: { label: 'System', cls: 'system' },
  approval_required: { label: 'System', cls: 'system' },
}

function StageBar({ episode, inv, evidenceCount, decided }) {
  const stages = [
    { name: 'Detected', detail: `day ${episode.start_day}`, done: true },
    { name: 'Investigating', detail: inv ? `${inv.tool_calls.length} tool call(s)` : 'not run', done: !!inv && inv.tool_calls.length > 0 },
    { name: 'Evidence', detail: inv ? `${evidenceCount} item(s)` : '—', done: !!inv && evidenceCount > 0 },
    { name: 'Synthesis', detail: inv ? inv.sufficiency.toLowerCase() : '—', done: !!inv && !!inv.narrative },
    { name: 'Human review', detail: inv ? inv.approval_status.toLowerCase().replace(/_/g, ' ') : '—', done: !!inv, current: !!inv && !decided },
    { name: 'Decision', detail: decided ? 'recorded' : 'pending', done: decided, final: true },
  ]
  return (
    <div className="stage-bar">
      {stages.map(s => (
        <div key={s.name}
          className={`stage ${s.done ? 'done' : ''} ${s.current ? 'current' : ''} ${s.final ? 'final' : ''}`}>
          <div className="s-name">{s.name}</div>
          <div className="s-detail">{s.detail}</div>
        </div>
      ))}
    </div>
  )
}

function HypothesesPanel({ hypotheses }) {
  const ORDER = ['RISK_DRIFT', 'LEGITIMATE_GROWTH', 'SEASONAL_PATTERN', 'INSUFFICIENT_EVIDENCE']
  return (
    <div>
      {ORDER.map(label => {
        const h = hypotheses[label]
        if (!h) return null
        const nSup = h.supporting_evidence_ids.length
        const nCon = h.contradicting_evidence_ids.length
        const investigated = nSup > 0 || nCon > 0 || h.support_score > 0
        return (
          <div key={label} className={`hyp ${h.status === 'LEADING' ? 'leading' : ''} ${investigated ? '' : 'not-investigated'}`}>
            <div className="hyp-top">
              <span className="hyp-name mono">{label}
                {h.status === 'LEADING' && <span className="lead">LEADING</span>}
              </span>
              <span className="hyp-meta">
                <span className="mono">{fmt(h.support_score)}</span>
                <span>{investigated ? 'investigated' : 'not investigated'}</span>
              </span>
            </div>
            <div className="bar"><div style={{ width: pct(h.support_score) }} /></div>
            <div className="sub">
              <span className="pos">+{nSup} supporting</span>
              <span className="neg">−{nCon} contradicting</span>
              <span className="muted2">{h.unresolved_questions.length} open question(s)</span>
            </div>
          </div>
        )
      })}
      <p className="muted2" style={{ fontSize: 11, marginTop: 8 }}>
        A hypothesis with zero evidence is <i>not investigated</i>, not disproven — sufficiency
        requires signal-group coverage before any conclusion is drawn.
      </p>
    </div>
  )
}

function AgentActivity({ auditEvents, investigationId }) {
  const events = useMemo(
    () => auditEvents.filter(e => e.investigation_id === investigationId),
    [auditEvents, investigationId])
  return (
    <div className="activity">
      {events.map(e => {
        const actor = ACTOR[e.event_type] || { label: 'System', cls: 'system' }
        let title = e.event_type, detail = ''
        const d = e.detail
        if (e.event_type === 'planner_decision') {
          title = d.selected_tool ? `Planner selected ${d.selected_tool}` : 'Planner stopped'
          detail = d.reason
        } else if (e.event_type === 'tool_call') {
          title = `Tool ${d.tool} — ${d.status}`
          detail = (d.evidence_ids || []).length ? `evidence registered: ${d.evidence_ids.join(', ')}` : (d.detail || d.question || '')
        } else if (e.event_type === 'hypothesis_update') {
          const movers = Object.entries(d.after || {})
            .filter(([k]) => Math.abs((d.after[k] || 0) - (d.before[k] || 0)) > 1e-9)
            .map(([k]) => `${k} ${(d.before[k] || 0).toFixed(2)}→${(d.after[k] || 0).toFixed(2)}`)
          title = 'Hypotheses re-scored'
          detail = movers.length ? movers.join(' · ') : 'no score change'
        } else if (e.event_type === 'recommendation') {
          title = `Recommendation: ${d.recommendation}`
          detail = `sufficiency ${d.sufficiency}`
        } else if (e.event_type === 'approval_required') {
          title = `Approval status: ${d.approval_status}`
        } else if (e.event_type === 'human_decision') {
          title = `Human decision: ${d.decision}`
          detail = d.reviewer_reason
        } else if (e.event_type === 'investigation_started') {
          title = 'Investigation started'
          detail = `episode ${d.episode_id}, as of day ${d.current_day}`
        } else if (e.event_type === 'loaded_episode_baseline_evidence') {
          title = 'Episode baseline loaded'
          detail = `${d.evidence_count} known missing-evidence gap(s) preloaded`
        }
        const fail = e.event_type === 'tool_call' && d.status === 'FAILURE'
        return (
          <div key={e.id || e.sequence} className={`step ${actor.cls} ${fail ? 'fail' : ''}`}>
            <div>
              <div className="a-actor">{actor.label} · seq {e.sequence}</div>
              <div className="a-title">{title}</div>
              {detail && <div className="a-detail">{detail}</div>}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function EvidencePanel({ evidence, hasInvestigation }) {
  const groups = useMemo(() => {
    const g = {}
    evidence.forEach(e => { (g[e.signal_group] = g[e.signal_group] || []).push(e) })
    return Object.entries(g)
  }, [evidence])

  if (!evidence.length) {
    return (
      <p className="muted" style={{ padding: 4 }}>
        {hasInvestigation
          ? 'This investigation ran before the current session — its registry view is not loaded. Re-run the investigation (deterministic, same result) to display the full evidence registry.'
          : 'No evidence gathered yet — run the investigation.'}
      </p>
    )
  }

  return (
    <div>
      {groups.map(([group, items]) => (
        <div key={group} className="ev-group">
          <div className="g-head">{group} <span className="muted2" style={{ fontWeight: 400 }}>· {items.length} item(s)</span></div>
          {items.map(e => {
            const stance = e.evidence_type === 'missing' ? 'MISSING'
              : e.supports_hypothesis === 'A' ? 'SUPPORTS RISK'
                : e.supports_hypothesis === 'B' ? 'CONTRADICTS RISK' : 'CONTEXT'
            const cls = e.evidence_type === 'missing' ? 'missing' : e.supports_hypothesis === 'A' ? 'A' : e.supports_hypothesis === 'B' ? 'B' : ''
            return (
              <div key={e.evidence_id} className={`ev-row ${cls}`}>
                <span className="ev-id mono">{e.evidence_id}</span>
                <div className="ev-main">
                  <div className="ev-line">
                    <Chip kind={stance === 'SUPPORTS RISK' ? 'red' : stance === 'CONTRADICTS RISK' ? 'green' : stance === 'MISSING' ? 'amber' : 'dim'}>{stance}</Chip>
                    <span className="ev-facts mono">
                      {e.metric}: <b>{e.value != null ? Number(e.value).toPrecision(4) : '—'}</b>
                      {' '}vs baseline <b>{e.baseline != null ? Number(e.baseline).toPrecision(4) : '—'}</b>
                      {e.deviation != null && <> · z <b>{e.deviation >= 0 ? '+' : ''}{Number(e.deviation).toFixed(2)}</b></>}
                      {' '}· {e.time_window}
                    </span>
                  </div>
                  <div className="interp">{e.interpretation}</div>
                </div>
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}

function AuditPanel({ episodeId }) {
  const [audit, setAudit] = useState(null)
  useEffect(() => { api.audit(episodeId).then(setAudit).catch(() => setAudit(null)) }, [episodeId])
  if (!audit) return <p className="muted" style={{ padding: 4 }}>Loading audit trail…</p>
  if (!audit.events.length) return <p className="muted" style={{ padding: 4 }}>No audit events yet.</p>
  return (
    <table className="grid audit-table">
      <thead>
        <tr><th>Time</th><th>Actor</th><th>Event</th><th>Object / result</th></tr>
      </thead>
      <tbody>
        {audit.events.map(e => {
          const actor = ACTOR[e.event_type] || { label: 'System' }
          const d = e.detail
          let obj = ''
          if (e.event_type === 'tool_call') obj = `${d.tool} — ${d.status}${(d.evidence_ids || []).length ? ` · ${d.evidence_ids.join(', ')}` : ''}`
          else if (e.event_type === 'planner_decision') obj = d.selected_tool ? `select ${d.selected_tool}` : 'stop'
          else if (e.event_type === 'recommendation') obj = `${d.recommendation} (sufficiency ${d.sufficiency})`
          else if (e.event_type === 'human_decision') obj = `${d.decision} — "${d.reviewer_reason}"`
          else if (e.event_type === 'approval_required') obj = d.approval_status
          else if (e.event_type === 'hypothesis_update') obj = 'recomputed from full evidence pool'
          else if (e.event_type === 'investigation_started') obj = `as of day ${d.current_day}`
          else obj = JSON.stringify(d).slice(0, 120)
          return (
            <tr key={e.id}>
              <td className="t mono">{(e.timestamp || '').slice(11, 19)}</td>
              <td className="actor"><Chip kind={actor.label === 'Human' ? 'green' : actor.label === 'Agent' ? 'blue' : 'dim'}>{actor.label}</Chip></td>
              <td className="etype mono">{e.event_type}</td>
              <td className="obj">{obj}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function EpisodePage({ episodeId, merchantId, openMerchant, back }) {
  const [ep, setEp] = useState(null)
  const [inv, setInv] = useState(null)
  const [evidence, setEvidence] = useState([])
  const [auditEvents, setAuditEvents] = useState([])
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [reason, setReason] = useState('')
  const [decision, setDecision] = useState(null)

  const load = () => api.episode(episodeId)
    .then(d => { setEp(d.episode); setInv(d.latest_investigation); setDecision(d.human_decisions[0] || null) })
    .catch(e => setError(e.message))
  useEffect(() => { load() }, [episodeId])

  const runInvestigation = () => {
    setBusy(true); setError(null)
    api.investigate(episodeId)
      .then(r => {
        setInv(r.investigation); setEvidence(r.evidence); setAuditEvents(r.audit_events)
      })
      .catch(e => setError(e.message))
      .finally(() => setBusy(false))
  }

  const recordDecision = (action) => {
    setBusy(true); setError(null)
    api.decide(episodeId, action, reason || 'Reviewed by risk operations.')
      .then(r => { setInv(r.investigation); setDecision(r.decision) })
      .catch(e => setError(e.message))
      .finally(() => setBusy(false))
  }

  // If an investigation already exists (e.g. arrived from the queue), load
  // its persisted evidence + audit once.
  useEffect(() => {
    if (inv && !evidence.length && !auditEvents.length) {
      api.audit(episodeId)
        .then(a => {
          setAuditEvents(a.events.filter(e => e.investigation_id === inv.investigation_id))
          // evidence comes from the investigate response only; for a
          // previously-persisted run, re-running is the documented way to
          // repopulate the registry view.
        })
        .catch(() => { })
    }
  }, [inv])

  if (error && !ep) return <ErrorBox error={error} />
  if (!ep) return <p className="muted">Loading episode…</p>

  const decided = inv && inv.approval_status !== 'PENDING_HUMAN_REVIEW'
  const leadingScore = inv ? inv.hypotheses[inv.leading_hypothesis].support_score : null
  const nSup = evidence.filter(e => e.supports_hypothesis === 'A').length
  const nCon = evidence.filter(e => e.supports_hypothesis === 'B').length
  const nMissing = evidence.filter(e => e.evidence_type === 'missing').length

  return (
    <div>
      <div className="case-head">
        <div className="row1">
          <span className="title mono">
            {merchantId} <span className="ep">/ {ep.episode_id}</span>
          </span>
          <div className="kv"><span className="k">Signals</span>
            <span className="v">{ep.signal_groups.length}</span></div>
          <div className="kv"><span className="k">Peak conf.</span>
            <span className="v mono">{fmt(ep.peak_score)}</span></div>
          <div className="kv"><span className="k">Episode state</span>
            <span className="v"><Chip kind={STATUS[ep.status]}>{ep.status}</Chip></span></div>
          <div className="kv"><span className="k">First detected</span>
            <span className="v mono">day {ep.start_day}</span></div>
          <div className="kv"><span className="k">Duration</span>
            <span className="v mono">{ep.current_day - ep.start_day} days</span></div>
          {inv && (
            <div className="kv"><span className="k">Risk score</span>
              <span className="v mono">{fmt(inv.hypotheses.RISK_DRIFT.support_score)}</span></div>
          )}
          <div className="kv"><span className="k">Trajectory</span>
            <ConfidenceSpark history={ep.confidence_history} /></div>
          <span className="spacer" />
          {!inv && <button className="btn primary" onClick={runInvestigation} disabled={busy}>
            {busy ? <span className="spin" /> : 'Run investigation'}
          </button>}
          {inv && <button className="btn" onClick={runInvestigation} disabled={busy}>
            {busy ? <span className="spin" /> : 'Re-run investigation'}
          </button>}
        </div>
        <StageBar episode={ep} inv={inv} evidenceCount={evidence.length} decided={decided} />
      </div>

      <div className={`reco-strip ${inv ? inv.recommendation : 'none'}`}>
        <div className="left">
          <div>
            <div className="r-label">Recommendation</div>
            <div className="r-value">{inv ? inv.recommendation : 'NOT YET INVESTIGATED'}</div>
            {inv && <div className="muted2" style={{ fontSize: 11, marginTop: 2 }}>
              leading: {inv.leading_hypothesis} ({fmt(leadingScore)}) · sufficiency {inv.sufficiency.toLowerCase()}
            </div>}
          </div>
        </div>
        <div className="why">
          {inv ? (
            <>
              <div className="kv"><span className="k">Supporting evidence</span><span className="v mono">{nSup}</span></div>
              <div className="kv"><span className="k">Contradicting</span><span className="v mono">{nCon}</span></div>
              <div className="kv"><span className="k">Missing</span><span className="v mono">{nMissing}</span></div>
              <div className="kv"><span className="k">Tool calls</span>
                <span className="v mono">{inv.budget.tool_calls_used}/{inv.budget.max_tool_calls}</span></div>
            </>
          ) : (
            <span className="muted">Run the investigation to gather evidence, score competing
              hypotheses, and produce a grounded recommendation.</span>
          )}
        </div>
        {inv && (
          <div className={`review-flag ${decided ? 'done' : ''}`}>
            {decided ? inv.approval_status : 'HUMAN REVIEW REQUIRED'}
          </div>
        )}
      </div>

      <div className="autonomy-note">
        <b>Recommendation only — no autonomous action.</b> Drift Watch has no code path that
        suspends, restricts, or contacts a merchant. Even an approved escalation only updates
        this review record; account actions are taken by humans outside this system.
      </div>

      <ErrorBox error={error} />

      {inv && (
        <>
          <div className="grid2">
            <div className="panel">
              <div className="panel-head"><h2>Competing hypotheses</h2>
                <span className="hint">recomputed from the full evidence pool after each tool call</span></div>
              <div className="panel-body"><HypothesesPanel hypotheses={inv.hypotheses} /></div>
            </div>
            <div className="panel">
              <div className="panel-head"><h2>Agent activity</h2>
                <span className="hint">bounded loop · planner mode {inv.planner_mode}</span></div>
              <div className="panel-body">
                <AgentActivity auditEvents={auditEvents} investigationId={inv.investigation_id} />
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-head"><h2>Evidence registry</h2>
              <span className="hint">{evidence.length} item(s) · stable IDs · traceable to source tool</span></div>
            <div className="panel-body"><EvidencePanel evidence={evidence} hasInvestigation={!!inv} /></div>
          </div>

          <div className="panel">
            <div className="panel-head"><h2>Grounded synthesis</h2>
              <span className="hint">every citation checked against the registry</span></div>
            <div className="panel-body">
              <div className="narrative">{inv.narrative}</div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-head"><h2>Human review</h2>
              <span className="hint">{decided ? 'decision recorded — final' : 'decision required'}</span></div>
            <div className="panel-body">
              {decided ? (
                decision ? (
                  <div className={`decision-strip ${decision.decision === 'APPROVE' ? '' : decision.decision === 'OVERRIDE' ? 'override' : 'more'}`}>
                    <div className="d-head">{decision.decision} — {inv.approval_status}</div>
                    <div className="d-meta">
                      {decision.decided_at} · original recommendation {decision.original_recommendation}
                      {decision.reviewer_reason ? <> · “{decision.reviewer_reason}”</> : null}
                      {' '}· recorded in the audit trail; no account action executed.
                    </div>
                  </div>
                ) : (
                  <p className="muted">A decision has been recorded for {inv.investigation_id} — see the audit trail below.</p>
                )
              ) : (
                <>
                  <table className="grid" style={{ maxWidth: 640, marginBottom: 6 }}>
                    <tbody>
                      <tr><td className="muted">Recommendation under review</td><td><b>{inv.recommendation}</b></td>
                        <td className="muted">Leading hypothesis</td><td>{inv.leading_hypothesis} ({fmt(leadingScore)})</td></tr>
                      <tr><td className="muted">Evidence</td><td className="mono">{nSup} supporting / {nCon} contradicting / {nMissing} missing</td>
                        <td className="muted">Sufficiency</td><td>{inv.sufficiency}</td></tr>
                    </tbody>
                  </table>
                  <textarea className="review-reason" rows="2" placeholder="Reviewer justification (recorded in the audit trail)"
                    value={reason} onChange={e => setReason(e.target.value)} />
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button className="btn approve" onClick={() => recordDecision('approve')} disabled={busy}>Approve escalation</button>
                    <button className="btn override" onClick={() => recordDecision('override')} disabled={busy}>Override</button>
                    <button className="btn more" onClick={() => recordDecision('request-evidence')} disabled={busy}>Request more evidence</button>
                  </div>
                </>
              )}
            </div>
          </div>

          <div className="panel">
            <div className="panel-head"><h2>Audit trail</h2>
              <span className="hint">persisted, ordered, immutable record of every step</span></div>
            <div className="panel-body tight"><AuditPanel episodeId={episodeId} /></div>
          </div>
        </>
      )}
    </div>
  )
}

/* ============================ shell ============================ */

const NAV = [
  { key: 'overview', label: 'Overview' },
  { key: 'queue', label: 'Risk queue' },
  { key: 'merchants', label: 'Merchants' },
]

export default function App() {
  const [view, setView] = useState({ name: 'overview' })
  const health = useHealth()
  const { data } = useMerchants()
  const pending = data ? data.summary.pending_human_review : 0
  const episodeCount = data ? data.summary.episodes_detected : 0

  const openMerchant = id => setView({ name: 'merchant', id })
  const openEpisode = (eid, mid) => setView({ name: 'episode', id: eid, merchantId: mid })
  const goto = key => setView({ name: key })

  const sectionTitle = {
    overview: 'Overview', queue: 'Risk Queue', merchants: 'Merchants',
    merchant: `Merchant ${view.id}`, episode: `Episode ${view.id}`,
  }[view.name]

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="name">Drift Watch</div>
          <div className="sub">Risk Operations</div>
        </div>
        <div className="nav-section">
          <div className="nav-label">Operations</div>
          {NAV.map(n => (
            <div key={n.key} className={`nav-item ${view.name === n.key ? 'active' : ''}`} onClick={() => goto(n.key)}>
              <span className="label">{n.label}</span>
              {n.key === 'queue' && episodeCount > 0 && <span className="count">{episodeCount}</span>}
              {n.key === 'overview' && pending > 0 && <span className="count">{pending}</span>}
            </div>
          ))}
        </div>
        <div className="nav-section">
          <div className="nav-label">Case</div>
          {view.name === 'merchant' && (
            <div className="nav-item active"><span className="label mono">{view.id}</span></div>
          )}
          {view.name === 'episode' && (
            <div className="nav-item active"><span className="label mono">{view.id.replace(/^DW-/, '')}</span></div>
          )}
        </div>
        <div className="foot">
          <div><span className={`dot ${health ? 'ok' : 'warn'}`} />engine {health ? (health.llm_provider === 'none' ? 'deterministic' : `llm:${health.llm_provider}`) : 'offline'}</div>
          <div>{health ? `${health.merchants} merchants · ${health.episodes} episodes` : 'connecting…'}</div>
        </div>
      </aside>

      <div className="main">
        <div className="topbar">
          <span className="section-title">{sectionTitle}</span>
          {view.name === 'episode' && (
            <span className="crumb">
              <a onClick={() => openMerchant(view.merchantId)}>{view.merchantId}</a> / {view.id}
            </span>
          )}
          {view.name === 'merchant' && <span className="crumb"><a onClick={() => goto('overview')}>merchants</a> / {view.id}</span>}
          <div className="runtime">
            <span className="item">db {health ? 'ok' : '—'}</span>
            <span className="item">api :8000</span>
            <span className="safety-flag"><span className="dot" />Human approval required — no autonomous actions</span>
          </div>
        </div>

        <div className="content">
          {view.name === 'overview' && <OverviewPage openMerchant={openMerchant} openEpisode={openEpisode} goto={goto} />}
          {view.name === 'queue' && <QueuePage openEpisode={openEpisode} />}
          {view.name === 'merchants' && <MerchantsPage openMerchant={openMerchant} />}
          {view.name === 'merchant' && <MerchantPage merchantId={view.id} openEpisode={openEpisode} back={() => goto('overview')} />}
          {view.name === 'episode' && (
            <EpisodePage episodeId={view.id} merchantId={view.merchantId}
              openMerchant={openMerchant} back={() => openMerchant(view.merchantId)} />
          )}
        </div>
      </div>
    </div>
  )
}
