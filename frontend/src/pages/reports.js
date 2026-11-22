import { api } from '../api/workspace.js';
import { heading } from '../components/common/heading.js';
import { empty, panel } from '../components/common/panel.js';
import { status } from '../components/common/status.js';
import { table } from '../components/common/table.js';
import { deltaChips, deltaPanel } from '../components/delta-panel.js';
import { resultDetail } from '../components/result-detail.js';
import { BASIS, BRANCH } from '../constants/domain.js';
import { poll } from '../hooks/poll.js';
import { state } from '../stores/workspace.js';
import { localTime, signed } from '../utils/format.js';
import { esc } from '../utils/html.js';

const OPEN = ['queued', 'running'];
const metricText = item => `实际差 ${signed(item.gap)} · 构成差 ${signed(item.composition)} · 系数差 ${signed(item.coefficient)}`;

function slotMeta(plan) {
  return `${BRANCH[plan.focus_branch]} − ${BRANCH[plan.control_branch]} · ${BASIS[plan.coefficient_ref]} · `
    + `${esc(plan.date_from)} → ${esc(plan.date_to)} · 每点 ≥ ${plan.min_samples} 张`;
}

function takeAlert() {
  const alert = state.alert;
  state.alert = '';
  return alert ? `<p class="inline-alert" role="alert">${esc(alert)}</p>` : '';
}

function flowLine(slot, canRun) {
  const parts = [status(slot.attention)];
  if (slot.job?.status === 'failed') parts.push(`<span class="subline failure">${esc(slot.job.failure)}</span>`);
  if (slot.attention === 'vacant') parts.push('<span class="subline">现值已交接，等待新候选稿发布；旧稿在详情中可查。</span>');
  if (slot.attention === 'idle') parts.push('<span class="subline">尚未产生候选稿，分析员可发起首次重算。</span>');
  const actions = [`<a class="text-btn" href="#/reports/${slot.plan_id}">打开周报 ↗</a>`];
  if (canRun) {
    if (!OPEN.includes(slot.job?.status)) actions.push(`<button class="text-btn" data-recompute="${slot.plan_id}">立即重算</button>`);
    if (slot.job?.status === 'failed') actions.push(`<button class="text-btn" data-retry="${slot.job.id}">重试</button>`);
  }
  return `<div class="slot-flow">${parts.join('')}<div class="row-actions">${actions.join('')}</div></div>`;
}

function slotCard(slot, canRun) {
  const current = slot.current ? `<div class="slot-metrics">
      <span>实际工时差 <b class="mono">${signed(slot.current.gap)}</b></span>
      <span>构成差 <b class="mono warm">${signed(slot.current.composition)}</b></span>
      <span>系数差 <b class="mono cool">${signed(slot.current.coefficient)}</b></span>
      <span class="subline">${slot.current.sample_count} 张 · ${esc(slot.current.published_by)} 发布于 ${localTime(slot.current.published_at)}</span>
    </div><div class="slot-delta"><span class="delta-label">较上一稿</span>${deltaChips(slot.current.delta)}</div>`
    : '<p class="slot-empty">暂无现值。</p>';
  return `<section class="panel report-slot"><header class="panel-head">
    <h2>${esc(slot.plan_key)} <small>v${slot.version}</small></h2><span>${esc(slot.label)}</span></header>
    <div class="slot-body"><p class="slot-meta">${slotMeta(slot)}</p>${current}${flowLine(slot, canRun)}</div></section>`;
}

function bindRunActions(view, refresh) {
  view.querySelectorAll('[data-recompute]').forEach(button => button.onclick = async () => {
    button.disabled = true;
    try {
      await api.recompute(Number(button.dataset.recompute));
      state.notice = '重算已提交。';
    } catch (error) {
      state.alert = error.message;
    }
    refresh();
  });
  view.querySelectorAll('[data-retry]').forEach(button => button.onclick = async () => {
    button.disabled = true;
    try {
      await api.retryJob(Number(button.dataset.retry));
      state.notice = '已重新排队，等待重算。';
    } catch (error) {
      state.alert = error.message;
    }
    refresh();
  });
}

async function listView({ view, active, refresh }) {
  const slots = await api.reports();
  if (!active()) return;
  const canRun = state.user.role === 'analyst';
  view.innerHTML = heading('周会复盘', '周报现值', '工票补录或修订后按原方案自动重算；候选稿发布后成为现值，旧稿永久可查。',
    '<button class="btn" data-reload>刷新</button>') + takeAlert()
    + (slots.length ? `<div class="slot-list">${slots.map(slot => slotCard(slot, canRun)).join('')}</div>`
      : empty('暂无周报口径', '保存一个比较方案版本后，这里会出现对应的周报槽位。', '<a class="btn" href="#/plans">打开对照组设置</a>'));
  view.querySelector('[data-reload]').onclick = refresh;
  bindRunActions(view, refresh);
  const pending = entries => entries.some(slot => slot.attention === 'recomputing');
  if (pending(slots)) poll(async () => {
    const entries = await api.reports();
    if (active()) refresh();
    return false;
  }, active);
}

function candidateRow(item, currentId, canPublish) {
  const chips = item.delta ? deltaChips(item.delta) : '<span class="chip">首稿</span>';
  return `<details class="candidate" data-candidate="${item.id}"><summary>
    <span class="mono candidate-id">C-${String(item.id).padStart(3, '0')}</span>${status(item.status)}
    ${item.id === currentId ? '<span class="chip current">现值</span>' : ''}
    <span class="candidate-metrics mono">${metricText(item)}</span>
    <span class="candidate-chips">${chips}</span>
    <span class="subline">${item.sample_count} 张 · 算于 ${localTime(item.computed_at)}</span>
    ${item.status === 'pending' && canPublish ? `<button class="btn primary" data-publish="${item.id}">发布为现值</button>` : ''}
    </summary><div class="candidate-body"><p class="loading">正在读取候选稿…</p></div></details>`;
}

function candidateDetail(detail) {
  return `<div class="candidate-detail">${resultDetail(detail.result)}
    <section class="panel delta-section"><header class="panel-head"><h2>较上一稿的变化</h2><span>快照 ${esc(detail.snapshot_sha.slice(0, 10))}</span></header>
    <div class="slot-body">${deltaPanel(detail.delta)}
    <div class="row-actions"><button class="text-btn" data-dl="csv">下载 CSV ↓</button>
    <button class="text-btn" data-dl="snapshot">下载快照 JSON ↓</button></div></div></section></div>`;
}

async function detailView({ id, view, active, refresh }) {
  const report = await api.report(id);
  if (!active()) return;
  const { plan, current, candidates, jobs } = report;
  const canRun = state.user.role === 'analyst';
  const canPublish = state.user.role === 'owner';
  const currentPanel = current ? panel('现值', `${plan.plan_key} v${plan.version} · ${current.sample_count} 张 · ${esc(current.published_by)} 发布于 ${localTime(current.published_at)}`,
    `${resultDetail(current.result)}<section class="panel delta-section"><header class="panel-head"><h2>较上一稿的变化</h2><span>快照 ${esc(current.snapshot_sha.slice(0, 10))}</span></header>
     <div class="slot-body">${deltaPanel(current.delta)}
     <div class="row-actions"><button class="text-btn" data-dl="csv" data-id="${current.id}">下载 CSV ↓</button>
     <button class="text-btn" data-dl="snapshot" data-id="${current.id}">下载快照 JSON ↓</button></div></div></section>`)
    : empty(report.history ? '现值待交接' : '尚无现值',
      report.history ? '跨周移票后现值已交接，等待新候选稿发布。旧稿仍在下方可查。' : '该口径还没有发布过现值。分析员可发起重算，业务方复核后发布。',
      canRun ? `<button class="btn primary" data-recompute="${plan.plan_id}">立即重算 ↗</button>` : '');
  const jobRows = jobs.map(job => [
    `<b class="mono">J-${String(job.id).padStart(3, '0')}</b>`, status(job.status), `${job.attempts} 次`,
    job.failure ? `<span class="failure">${esc(job.failure)}</span>` : '—',
    esc(localTime(job.created_at)), esc(localTime(job.finished_at)),
    job.status === 'failed' && canRun ? `<button class="text-btn" data-retry="${job.id}">重试</button>` : '—',
  ]);
  view.innerHTML = heading('周会复盘', `${plan.plan_key} · v${plan.version}`, slotMeta(plan),
    `${canRun && !OPEN.includes(jobs[0]?.status) ? `<button class="btn" data-recompute="${plan.plan_id}">立即重算</button>` : ''}
     <a class="btn" href="#/reports">返回周报列表</a>`) + takeAlert()
    + `<div class="report-head">${status(report.attention)}${jobs[0]?.status === 'failed' ? `<span class="subline failure">${esc(jobs[0].failure)}</span>` : ''}</div>`
    + currentPanel
    + panel('候选稿与旧稿', `${candidates.length} 稿`, candidates.length
      ? `<div class="candidate-list">${candidates.map(item => candidateRow(item, plan.current_candidate_id, canPublish)).join('')}</div>`
      : '<p class="field-note slot-body">暂无候选稿。工票变动触发重算后，候选稿会出现在这里。</p>')
    + (jobs.length ? panel('重算任务', `${jobs.length} 条`, `<p class="inline-alert" data-poll-error></p>`
      + table(['任务', '状态', '尝试', '失败原因', '发起时间', '完成时间', '操作'], jobRows, '')) : '');
  view.querySelectorAll('[data-recompute]').forEach(button => button.onclick = async () => {
    button.disabled = true;
    try {
      await api.recompute(Number(button.dataset.recompute));
      state.notice = '重算已提交。';
    } catch (error) {
      state.alert = error.message;
    }
    refresh();
  });
  view.querySelectorAll('[data-retry]').forEach(button => button.onclick = async () => {
    button.disabled = true;
    try {
      await api.retryJob(Number(button.dataset.retry));
      state.notice = '已重新排队，等待重算。';
    } catch (error) {
      state.alert = error.message;
    }
    refresh();
  });
  view.querySelectorAll('[data-publish]').forEach(button => button.onclick = async event => {
    event.preventDefault();
    button.disabled = true;
    try {
      const result = await api.publishCandidate(Number(button.dataset.publish));
      state.notice = result.vacated?.length
        ? `已发布为现值；${result.vacated.map(item => `${item.plan_key} v${item.version}`).join('、')} 的现值已交接，待其重算发布。`
        : '已发布为现值。';
    } catch (error) {
      state.alert = error.message;
    }
    refresh();
  });
  view.querySelectorAll('details.candidate').forEach(item => item.addEventListener('toggle', async () => {
    if (!item.open || item.dataset.loaded) return;
    item.dataset.loaded = '1';
    const body = item.querySelector('.candidate-body');
    try {
      const detail = await api.candidate(Number(item.dataset.candidate));
      if (!active()) return;
      body.innerHTML = candidateDetail(detail);
      bindDownloads(body);
    } catch (error) {
      body.innerHTML = `<p class="inline-alert">${esc(error.message)}</p>`;
    }
  }));
  const bindDownloads = container => container.querySelectorAll('[data-dl]').forEach(button => button.onclick = async () => {
    const candidateId = Number(button.dataset.id || button.closest('details.candidate')?.dataset.candidate);
    try {
      if (button.dataset.dl === 'csv') await api.exportCandidate(candidateId);
      else await api.candidateSnapshot(candidateId);
    } catch (error) {
      state.alert = error.message;
      refresh();
    }
  });
  bindDownloads(view);
  if (jobs.some(job => OPEN.includes(job.status))) poll(async () => {
    await api.report(id);
    if (active()) refresh();
    return false;
  }, active);
}

export async function reports(context) {
  if (context.id) await detailView(context);
  else await listView(context);
}
