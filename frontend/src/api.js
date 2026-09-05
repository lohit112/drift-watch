const JSON_HEADERS = { 'Content-Type': 'application/json' }

async function handle(resp) {
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`
    try {
      const body = await resp.json()
      if (body && body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* keep default */ }
    throw new Error(detail)
  }
  return resp.json()
}

export const api = {
  health: () => fetch('/health').then(handle),
  merchants: () => fetch('/merchants').then(handle),
  merchant: (id) => fetch(`/merchants/${id}`).then(handle),
  merchantEpisodes: (id) => fetch(`/merchants/${id}/episodes`).then(handle),
  episode: (id) => fetch(`/episodes/${id}`).then(handle),
  investigate: (episodeId) =>
    fetch(`/episodes/${episodeId}/investigate`, { method: 'POST' }).then(handle),
  decide: (episodeId, action, reviewerReason) =>
    fetch(`/episodes/${episodeId}/${action}`, {
      method: 'POST', headers: JSON_HEADERS,
      body: JSON.stringify({ reviewer_reason: reviewerReason }),
    }).then(handle),
  audit: (episodeId) => fetch(`/episodes/${episodeId}/audit`).then(handle),
}
