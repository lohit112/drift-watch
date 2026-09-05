import React, { useEffect, useState } from 'react'
import { api } from './api.js'

const RECOMMENDATION_STYLE = {
  ESCALATE: 'red', REQUEST_MORE_EVIDENCE: 'amber', MONITOR: 'green',
}
const STATUS_STYLE = {
  WATCH: 'blue', INVESTIGATING: 'amber', ESCALATE: 'red', RESOLVED: 'green',
}

function Chip({ kind, children }) {
  return <span className={`chip ${kind || ''}`}>{children}</span>
}

function ErrorBox({ error }) {
  if (!error) return null
  return <div className="error-box">⚠ {error}</div>
}

/* ---------------- Dashboard ---------------- */

function Dashboard({ openMerchant }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => { api.merchants().then(setData).catch(e => setError(e.message)) }, [])

  if (error) return <ErrorBox error={error} />
  if (!data) return <p className="muted">Loading…</p>
  const s = data.summary

  return (
    <div>
      <div className="metrics">
        <div className="metric"><div className="v mono">{s.merchants_monitored}</div><div className="l">Merchants monitored</div></div>
        <div className="metric"><div className="v mono">{s.episodes_detected}</div><div className="l">Risk episodes detected</div></div>
        <div className="metric"><div className="v mono">{s.investigations_run}</div><div className="l">Investigations run</div></div>
        <div className="metric"><div className="v mono">{s.escalations_recommended}</div><div className="l">Escalations recommended</div></div>
        <div className="metric"><div className="v mono">{s.pending_human_review}</div><div className="l">Pending human review</div></div>
        <div className="metric"><div className="v mono">{s.approved}/{s.overridden}</div><div className="l">Human approved / overridden</div></div>
      </div>

      <div className="panel">
        <h2>Merchants — behavioral drift monitoring</h2>
        <table>
          <thead>
            <tr>
              <th>Merchant</th><th>Category</th><th>Geography</th><th>Period</th>
              <th>Episodes</th><th>Latest episode</th><th>Status</th>
            </tr>
          </thead>
          <tbody>
            {data.merchants.map(m => (
              <tr key={m.merchant_id} className="clickable" onClick={() => openMerchant(m.merchant_id)}>
                <td className="mono">{m.merchant_id}</td>
                <td>{m.dominant_category}</td>
                <td>{m.dominant_geo}</td>
                <td className="mono">days {m.first_day}–{m.last_day}</td>
                <td className="mono">{m.episode_count}</td>
                <td className="mono">{m.latest_episode_id || '—'}</td>
                <td>{m.latest_episode_status ? <Chip kind={STATUS_STYLE[m.latest_episode_status]}>{m.latest_episode_status}</Chip> : <span className="muted">clean</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/* ---------------- Timeline (SVG) ---------------- */

function Timeline({ points, episode }) {
  if (!points || !points.length) return null
  const W = 900, H = 130, PAD = 6
  const days = points.map(p => p.day)
  const d0 = Math.min(...days), d1 = Math.max(...days)
  const x = day => PAD + ((day - d0) / (d1 - d0)) * (W - 2 * PAD)

  const series = [
    { key: 'txn_count', label: 'txn count', color: '#2b84eb' },
    { key: 'refund_rate', label: 'refund rate', color: '#e79b13' },
    { key: 'dispute_rate', label: 'dispute rate', color: '#e5484d' },
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
  const epStart = episode ? x(episode.start_day) : null
  const epEnd = episode ? x(episode.current_day) : null

  return (
    <div className="timeline">
      <svg viewBox={`0 0 ${W} ${H + 18}`} preserveAspectRatio="none">
        {series.map(s => (
          <path key={s.key} d={pathFor(s.key)} fill="none" stroke={s.color} strokeWidth="1.4" opacity="0.9" />
        ))}
        {epStart != null && (
          <rect x={epStart} y={0} width={Math.max(2, epEnd - epStart)} height={H} fill="rgba(229,72,77,0.08)" stroke="rgba(229,72,77,0.45)" strokeDasharray="4 3" />
        )}
        {driftDays.map(d => (
          <line key={d} x1={x(d)} y1={0} x2={x(d)} y2={H} stroke="#e5484d" strokeWidth="1" opacity="0.55" />
        ))}
        <line x1={0} y1={H + 8} x2={W} y2={H + 8} stroke="#dbe4ef" />
      </svg>
      <div className="legend">
        {series.map(s => <span key={s.key} style={{ color: s.color, marginRight: 14 }}>— {s.label}</span>)}
        <span style={{ color: '#e5484d', marginRight: 14 }}>| detector-flagged day</span>
        <span style={{ color: '#e5484d' }}>▢ highlighted span: selected episode</span>
      </div>
    </div>
  )
}

/* ---------------- Merchant detail ---------------- */

function MerchantDetail({ merchantId, openEpisode, back }) {
  const [detail, setDetail] = useState(null)
  const [latest, setLatest] = useState({})
  const [error, setError] = useState(null)

  useEffect(() => {
    api.merchant(merchantId).then(setDetail).catch(e => setError(e.message))
    api.merchantEpisodes(merchantId).then(r => setLatest(r.latest_investigations || {})).catch(() => {})
  }, [merchantId])

  if (error) return <ErrorBox error={error} />
  if (!detail) return <p className="muted">Loading…</p>

  return (
    <div>
      <div className="crumbs"><a onClick={back}>← Dashboard</a> / merchant {detail.merchant_id}</div>
      <div className="panel">
        <h2>Merchant identity</h2>
        <table style={{ maxWidth: 640 }}>
          <tbody>
            <tr><td className="muted">Merchant ID</td><td className="mono">{detail.merchant_id}</td></tr>
            <tr><td className="muted">Dominant category</td><td>{detail.dominant_category}</td></tr>
            <tr><td className="muted">Dominant geography</td><td>{detail.dominant_geo}</td></tr>
            <tr><td className="muted">Observation window</td><td className="mono">day {detail.first_day} – {detail.last_day}</td></tr>
            <tr><td className="muted">Risk episodes</td><td className="mono">{detail.episodes.length}</td></tr>
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2>Behavioral timeline — vs. the merchant's own baseline</h2>
        <Timeline points={detail.behavioral_timeline} episode={detail.episodes[detail.episodes.length - 1]} />
        <p className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>
          Each series is normalized to its own range; what matters is the <i>deviation from this merchant's own
          trailing baseline</i>, not the absolute level. Red ticks mark days the detector flagged.
        </p>
      </div>

      <div className="panel">
        <h2>Risk episodes</h2>
        {detail.episodes.length === 0 && <p className="muted">No drift episodes detected for this merchant.</p>}
        <table>
          <thead>
            <tr><th>Episode</th><th>Window</th><th>Signals deviating</th><th>Peak confidence</th><th>Status</th><th>Latest recommendation</th><th></th></tr>
          </thead>
          <tbody>
            {detail.episodes.map(e => {
              const inv = latest[e.episode_id]
              return (
                <tr key={e.episode_id} className="clickable" onClick={() => openEpisode(e.episode_id, merchantId)}>
                  <td className="mono">{e.episode_id}</td>
                  <td className="mono">days {e.start_day}–{e.current_day}</td>
                  <td>{e.signal_groups.map(g => <Chip key={g}>{g}</Chip>)}{' '}</td>
                  <td className="mono">{e.peak_score != null ? e.peak_score.toFixed(3) : '—'}</td>
                  <td><Chip kind={STATUS_STYLE[e.status]}>{e.status}</Chip></td>
                  <td>{inv ? <Chip kind={RECOMMENDATION_STYLE[inv.recommendation]}>{inv.recommendation}</Chip> : <span className="muted">not investigated</span>}</td>
                  <td><button className="link">open →</button></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/* ---------------- Episode / Investigation view ---------------- */

const HYP_ORDER = ['RISK_DRIFT', 'LEGITIMATE_GROWTH', 'SEASONAL_PATTERN', 'INSUFFICIENT_EVIDENCE']

function Hypotheses({ hypotheses }) {
  return (
    <div>
      {HYP_ORDER.map(label => {
        const h = hypotheses[label]
        if (!h) return null
        const pct = Math.round((h.support_score || 0) * 100)
        return (
          <div key={label} className={`hyp-row ${h.status === 'LEADING' ? 'leading' : ''}`}>
            <span className="name mono">{label}{h.status === 'LEADING' ? '  ▲ leading' : ''}</span>
            <div className="bar"><div style={{ width: `${pct}%` }} /></div>
            <span className="score mono">{(h.support_score || 0).toFixed(3)}</span>
          </div>
        )
      })}
    </div>
  )
}

function EvidenceList({ evidence }) {
  const supporting = evidence.filter(e => e.supports_hypothesis === 'A')
  const contradicting = evidence.filter(e => e.supports_hypothesis === 'B')
  const missing = evidence.filter(e => e.evidence_type === 'missing')
  const contextual = evidence.filter(e => e.supports_hypothesis == null && e.evidence_type !== 'missing')
  const group = (title, items, tone) => (
    <div>
      <h3>{title} <span className="muted">({items.length})</span></h3>
      {items.length === 0 && <p className="muted" style={{ fontSize: 12 }}>none</p>}
      {items.map(e => (
        <div key={e.evidence_id} className={`ev ${e.supports_hypothesis === 'A' ? 'A' : e.supports_hypothesis === 'B' ? 'B' : 'none'}`}>
          <span className="id mono">{e.evidence_id}</span>
          <span className="type">{e.evidence_type} · {e.signal_group} · via {e.source_tool}</span>
          <div className="interp">{e.interpretation}</div>
        </div>
      ))}
    </div>
  )
  return (
    <div>
      {group('Supporting evidence (Hypothesis A — risk drift)', supporting)}
      {group('Contradicting / competing evidence (Hypothesis B — legitimate explanation)', contradicting)}
      {group('Missing evidence — dimensions that could not be assessed', missing)}
      {group('Contextual / historical', contextual)}
    </div>
  )
}

function ToolActivity({ investigation }) {
  return (
    <div className="tool-activity">
      {investigation.tool_calls.length === 0 && <p className="muted">No tool calls (investigation failed before any tool ran).</p>}
      {investigation.tool_calls.map(t => (
        <div key={t.sequence} className={`tool-step ${t.status === 'FAILURE' ? 'fail' : ''}`}>
          <span className="n mono">{t.sequence}.</span>
          <div>
            <div><span className="mono">{t.tool_name}</span>{' '}
              <Chip kind={t.status === 'SUCCESS' ? 'green' : 'red'}>{t.status}</Chip>
              {t.failure_reason && <Chip kind="red">{t.failure_reason}</Chip>}
            </div>
            <div className="q">“{t.question}”</div>
            {t.evidence_ids_produced.length > 0 &&
              <div className="q mono">→ {t.evidence_ids_produced.join(', ')}</div>}
          </div>
        </div>
      ))}
      <p className="muted" style={{ fontSize: 12, margin: '4px 0 0' }}>
        Planner mode: <b>{investigation.planner_mode}</b> · budget used {investigation.budget.tool_calls_used}/{investigation.budget.max_tool_calls} tool calls,
        {' '}{investigation.budget.iterations_used}/{investigation.budget.max_iterations} iterations · sufficiency: {investigation.sufficiency}
      </p>
    </div>
  )
}

function AuditTrail({ episodeId }) {
  const [audit, setAudit] = useState(null)
  useEffect(() => { api.audit(episodeId).then(setAudit).catch(() => {}) }, [episodeId])
  if (!audit) return <p className="muted">Loading audit trail…</p>
  return (
    <div className="audit-list">
      {audit.events.map(e => (
        <div key={e.id} className="audit-item">
          <span className="seq mono">{e.sequence}</span>
          <span className="etype mono">{e.event_type}</span>
          <span className="detail mono">{JSON.stringify(e.detail).slice(0, 220)}</span>
        </div>
      ))}
    </div>
  )
}

function EpisodeView({ episodeId, merchantId, openMerchant, back }) {
  const [ep, setEp] = useState(null)
  const [inv, setInv] = useState(null)
  const [evidence, setEvidence] = useState([])
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [reason, setReason] = useState('')
  const [decision, setDecision] = useState(null)

  const loadEpisode = () => api.episode(episodeId).then(d => {
    setEp(d.episode)
    setInv(d.latest_investigation)
  }).catch(e => setError(e.message))

  useEffect(() => { loadEpisode() }, [episodeId])

  const runInvestigation = () => {
    setBusy(true); setError(null)
    api.investigate(episodeId)
      .then(r => { setInv(r.investigation); setEvidence(r.evidence) })
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

  if (error && !ep) return <ErrorBox error={error} />
  if (!ep) return <p className="muted">Loading…</p>

  const decided = inv && inv.approval_status !== 'PENDING_HUMAN_REVIEW'
  const hyps = inv ? inv.hypotheses : null

  return (
    <div>
      <div className="crumbs">
        <a onClick={() => openMerchant(merchantId)}>← {merchantId}</a> / episode {episodeId}
      </div>

      <div className="panel">
        <h2>Episode summary</h2>
        <table style={{ maxWidth: 760 }}>
          <tbody>
            <tr><td className="muted">Episode</td><td className="mono">{ep.episode_id}</td></tr>
            <tr><td className="muted">Window</td><td className="mono">days {ep.start_day} – {ep.current_day}{ep.end_day ? ` (resolved day ${ep.end_day})` : ''}</td></tr>
            <tr><td className="muted">Deviating signal groups</td><td>{ep.signal_groups.map(g => <Chip key={g}>{g}</Chip>)}</td></tr>
            <tr><td className="muted">Peak confidence (deterministic layer)</td><td className="mono">{ep.peak_score != null ? ep.peak_score.toFixed(3) : '—'} on day {ep.peak_day}</td></tr>
            <tr><td className="muted">Episode status</td><td><Chip kind={STATUS_STYLE[ep.status]}>{ep.status}</Chip></td></tr>
          </tbody>
        </table>
      </div>

      {!inv && (
        <div className="panel">
          <h2>Investigation</h2>
          <p className="muted">No investigation has been run for this episode yet.</p>
          <button className="btn primary" onClick={runInvestigation} disabled={busy}>
            {busy ? <span className="spin" /> : '🔎'} Investigate episode
          </button>
        </div>
      )}

      {inv && (
        <>
          <div className={`reco-banner ${inv.recommendation}`}>
            <div>
              <div className="l muted" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Recommendation</div>
              <div className="big mono">{inv.recommendation}</div>
            </div>
            <div>
              <div className="l muted" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Approval status</div>
              <div><Chip kind={decided ? 'green' : 'amber'}>{inv.approval_status}</Chip></div>
            </div>
            <div>
              <div className="l muted" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Leading hypothesis</div>
              <div className="mono">{inv.leading_hypothesis}</div>
            </div>
            <div style={{ marginLeft: 'auto' }}>
              <button className="btn" onClick={runInvestigation} disabled={busy}>
                {busy ? <span className="spin" /> : '↻'} Re-run investigation
              </button>
            </div>
          </div>

          <div className="autonomy-note">
            <b>Drift Watch only recommends — it cannot act.</b> An ESCALATE recommendation does not suspend,
            restrict, or contact anyone. The system has no code path to execute an account action: only a human
            reviewer's recorded decision (below) moves a case forward, and even that only updates this review
            record. Any account action is taken by humans outside this system.
          </div>

          <div className="grid2">
            <div className="panel">
              <h2>Competing hypotheses (evidence-scored)</h2>
              {hyps ? <Hypotheses hypotheses={hyps} /> : <p className="muted">—</p>}
              <p className="muted" style={{ fontSize: 12 }}>
                Scores are recomputed from the full evidence pool after every tool call. RISK_DRIFT reuses the
                Phase 2 confidence model unchanged; competing hypotheses accumulate only evidence actually
                gathered during this investigation.
              </p>
            </div>
            <div className="panel">
              <h2>Planner / tool activity</h2>
              <ToolActivity investigation={inv} />
            </div>
          </div>

          <div className="panel">
            <h2>Grounded synthesis — every claim cites registered evidence</h2>
            <div className="narrative">{inv.narrative}</div>
          </div>

          <div className="panel"><h2>Evidence registry</h2><EvidenceList evidence={evidence} /></div>

          <div className="panel">
            <h2>Human review {decided ? '— decision recorded' : '— required'}</h2>
            {decided ? (
              decision ? (
                <div className={`decision-box ${decision.decision === 'APPROVE' ? '' : decision.decision === 'OVERRIDE' ? 'override' : 'more'}`}>
                  <b>{decision.decision}</b> recorded by human reviewer for {inv.investigation_id}:
                  “{decision.reviewer_reason}”.
                  <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                    Original recommendation: {decision.original_recommendation}. This decision is recorded in the
                    audit trail; it does not execute any account action.
                  </div>
                </div>
              ) : (
                <p className="muted">A human decision has been recorded for this investigation — see the audit trail below.</p>
              )
            ) : (
              <>
                <p className="muted">
                  A human risk reviewer must decide. The recommendation is advisory; the final decision — and any
                  action outside this system — is the reviewer's.
                </p>
                <textarea className="review-reason" rows="2" placeholder="Reviewer justification (recorded in the audit trail)"
                  value={reason} onChange={e => setReason(e.target.value)} />
                <div style={{ display: 'flex', gap: 10 }}>
                  <button className="btn approve" onClick={() => recordDecision('approve')} disabled={busy}>✔ Approve escalation</button>
                  <button className="btn override" onClick={() => recordDecision('override')} disabled={busy}>✖ Override</button>
                  <button className="btn more" onClick={() => recordDecision('request-evidence')} disabled={busy}>＋ Request more evidence</button>
                </div>
              </>
            )}
          </div>

          <div className="panel">
            <h2>Audit trail — every investigation step, in order</h2>
            <AuditTrail episodeId={episodeId} />
          </div>
        </>
      )}
      <ErrorBox error={error} />
    </div>
  )
}

/* ---------------- App shell ---------------- */

export default function App() {
  const [view, setView] = useState({ name: 'dashboard' })
  const [health, setHealth] = useState(null)

  useEffect(() => { api.health().then(setHealth).catch(() => setHealth({ status: 'unreachable' })) }, [])

  return (
    <div>
      <header className="topbar">
        <h1><span className="logo">⏱ Drift Watch</span></h1>
        <span className="tag">Risk Operations</span>
        <span className="tag">phase 5 · {health ? (health.llm_provider === 'none' ? 'deterministic engine' : `LLM: ${health.llm_provider}`) : '…'}</span>
        <span className="safety">Recommendations only — a human always decides. No autonomous account actions.</span>
      </header>
      <main>
        {view.name === 'dashboard' && (
          <Dashboard openMerchant={(id) => setView({ name: 'merchant', id })} />
        )}
        {view.name === 'merchant' && (
          <MerchantDetail
            merchantId={view.id}
            openEpisode={(eid, mid) => setView({ name: 'episode', id: eid, merchantId: mid })}
            back={() => setView({ name: 'dashboard' })}
          />
        )}
        {view.name === 'episode' && (
          <EpisodeView
            episodeId={view.id}
            merchantId={view.merchantId}
            openMerchant={(id) => setView({ name: 'merchant', id })}
            back={() => setView({ name: 'merchant', id: view.merchantId })}
          />
        )}
      </main>
    </div>
  )
}
