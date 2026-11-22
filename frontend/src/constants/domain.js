export const BRANCH = { north: '北埠修伞铺', south: '南桥修伞铺' };
export const ROLE = { owner: '业务方', analyst: '分析员', observer: '观察员' };
export const BASIS = { control: '对照网点系数', focus: '比较网点系数' };
export const RUN_STATUS = { queued: '排队中', running: '计算中', completed: '已完成', failed: '待补正' };
export const DRAFT_STATUS = { draft: '待发布', published: '已发布' };
export const CANDIDATE_STATUS = { pending: '候选待发布', published: '已发布', stale: '已过期' };
export const JOB_STATUS = { queued: '排队中', running: '重算中', done: '已完成', failed: '待补正' };
export const ATTENTION = {
  recomputing: '重算中', awaiting_publish: '候选待发布', failed: '重算待补正',
  vacant: '现值待交接', outdated: '样本已更新', idle: '尚未开算', current: '现值有效',
};
export const TICKET_FIELD = { branch: '网点', worked_on: '返修日期', ribs: '换骨 / 根', fabric: '布损 / 处', mechanism: '开合机构', minutes: '工时 / 分', note: '备注' };
export const TERMS = { intercept: '基础工时', ribs: '伞骨更换', fabric: '布面损伤', mechanism: '开合机构' };
export const TERM_UNIT = { intercept: '常数项', ribs: '根', fabric: '处', mechanism: '需修 = 1' };
export const DATE_FROM = '2026-11-09';
export const DATE_TO = '2026-11-15';
