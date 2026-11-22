/** @typedef {{username: string, display_name: string, role: 'owner'|'analyst'|'observer'}} User */
/** @typedef {{code: string, branch: 'north'|'south', worked_on: string, ribs: number, fabric: number, mechanism: number, minutes: number, note: string, revision: number}} Ticket */
/** @typedef {{id: number, plan_key: string, version: number, label: string, focus_branch: string, control_branch: string, coefficient_ref: 'focus'|'control', date_from: string, date_to: string, min_samples: number}} Plan */
/** @typedef {{id: number, status: 'queued'|'running'|'completed'|'failed', plan: Plan, sample_count: number, snapshot_sha: string}} Run */
/** @typedef {{entered: string[], exited: string[], modified: {code: string, from_revision: number, to_revision: number, changes: Object.<string, *[]>}[], metrics: Object.<string, {before: number, after: number, change: number}>}} Delta */
/** @typedef {{id: number, plan_id: number, sample_seq: number, status: 'pending'|'published'|'stale', sample_count: number, snapshot_sha: string, gap: number, composition: number, coefficient: number, delta: Delta|null}} Candidate */
/** @typedef {{id: number, plan_id: number, status: 'queued'|'running'|'done'|'failed', failure: string|null, attempts: number}} ReportJob */
export {};
