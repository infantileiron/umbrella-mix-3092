import { BRANCH, TICKET_FIELD } from '../constants/domain.js';
import { number, signed } from '../utils/format.js';
import { esc } from '../utils/html.js';
import { table } from './common/table.js';

export function deltaChips(delta) {
  if (!delta) return '<span class="chip">首稿</span>';
  return `<span class="chip in">进 ${delta.entered.length} 票</span>`
    + `<span class="chip out">出 ${delta.exited.length} 票</span>`
    + `<span class="chip mod">改 ${delta.modified.length} 票</span>`
    + `<span class="chip">构成差 ${signed(delta.metrics.composition.change)}</span>`
    + `<span class="chip">系数差 ${signed(delta.metrics.coefficient.change)}</span>`;
}

function fieldText(key, value) {
  if (key === 'branch') return BRANCH[value];
  if (key === 'mechanism') return value ? '需修' : '无需修';
  return esc(String(value));
}

export function deltaPanel(delta) {
  if (!delta) return '<p class="field-note">首稿：该口径的第一版现值，无上一版可对照。</p>';
  const metrics = table(['指标', '上一稿', '本稿', '变化（分钟/票）'],
    [['实际工时差', 'gap'], ['构成差', 'composition'], ['系数差', 'coefficient']].map(([label, key]) => {
      const metric = delta.metrics[key];
      return [label, number(metric.before), number(metric.after), `<b class="mono">${signed(metric.change)}</b>`];
    }), undefined, 'delta-metrics');
  const codes = list => (list.length ? list.map(code => `<code>${esc(code)}</code>`).join(' ') : '—');
  const modified = delta.modified.length ? table(['工票', '修订号', '改动内容'], delta.modified.map(item => [
    `<b class="mono">${esc(item.code)}</b>`, `r${item.from_revision} → r${item.to_revision}`,
    Object.entries(item.changes).map(([key, [old, current]]) =>
      `${TICKET_FIELD[key] || key}：${fieldText(key, old)} → ${fieldText(key, current)}`).join('；'),
  ]), '', 'delta-modified') : '';
  return `<div class="delta-panel">${metrics}
    <div class="delta-lists">
      <p><b>进入样本</b><span>${codes(delta.entered)}</span></p>
      <p><b>退出样本</b><span>${codes(delta.exited)}</span></p>
    </div>${modified}</div>`;
}
