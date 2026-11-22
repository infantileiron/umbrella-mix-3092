import { ATTENTION, CANDIDATE_STATUS, DRAFT_STATUS, JOB_STATUS, RUN_STATUS } from '../../constants/domain.js';
import { esc } from '../../utils/html.js';

export function status(value) {
  const label = RUN_STATUS[value] || DRAFT_STATUS[value] || CANDIDATE_STATUS[value] || JOB_STATUS[value]
    || ATTENTION[value] || '待复核';
  return `<span class="status ${esc(value)}"><i></i>${esc(label)}</span>`;
}
