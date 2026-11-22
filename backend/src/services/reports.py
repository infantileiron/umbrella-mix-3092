import json
import logging

from fastapi import HTTPException

from src.constants.domain import METHOD, CandidateStatus, JobStatus, Role
from src.models.db import transaction
from src.models.queries import CANDIDATE_COLUMNS, JOB_COLUMNS, PLAN_COLUMNS, TICKET_COLUMNS
from src.services.audit import record
from src.services.decomposition import AnalysisError, analyze
from src.utils.queue import wake_worker
from src.utils.serialization import canonical, checksum

logger = logging.getLogger(__name__)
TICKET_FIELDS = ('branch', 'worked_on', 'ribs', 'fabric', 'mechanism', 'minutes', 'note')
METRIC_KEYS = ('gap', 'composition', 'coefficient')


class ClaimLost(Exception):
    pass


def ensure_slots(cursor):
    cursor.execute('INSERT IGNORE INTO report_slots (plan_id) SELECT id FROM comparison_plans')


def note_ticket_change(cursor, *, code, revision, kind, actor, prev, new):
    """在工票写入的同一事务内登记修订流水，并把受影响的周报槽位推进到新样本水位。"""
    cursor.execute('INSERT INTO ticket_changes (code, revision, kind, actor, prev_branch, prev_worked_on, '
                   'new_branch, new_worked_on) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                   (code, revision, kind, actor, prev and prev['branch'], prev and prev['worked_on'],
                    new['branch'], new['worked_on']))
    seq = cursor.lastrowid
    pairs = {(new['branch'], new['worked_on'])}
    if prev:
        pairs.add((prev['branch'], prev['worked_on']))
    plan_ids = set()
    for branch, worked_on in pairs:
        cursor.execute('SELECT s.plan_id FROM report_slots s JOIN comparison_plans p ON p.id = s.plan_id '
                       'WHERE (p.focus_branch = %s OR p.control_branch = %s) AND %s BETWEEN p.date_from AND p.date_to',
                       (branch, branch, worked_on))
        plan_ids.update(row['plan_id'] for row in cursor.fetchall())
    if not plan_ids:
        return
    ordered = sorted(plan_ids)
    marks = ','.join(['%s'] * len(ordered))
    cursor.execute(f'SELECT plan_id FROM report_slots WHERE plan_id IN ({marks}) ORDER BY plan_id FOR UPDATE', ordered)
    cursor.execute(f'UPDATE report_slots SET sample_seq = GREATEST(sample_seq, %s), updated_at = UTC_TIMESTAMP(6) '
                   f'WHERE plan_id IN ({marks})', (seq, *ordered))
    cursor.execute(f"UPDATE report_candidates SET status = 'stale' WHERE plan_id IN ({marks}) AND status = 'pending'",
                   ordered)
    cursor.execute(f'SELECT s.plan_id FROM report_slots s WHERE s.plan_id IN ({marks}) AND ('
                   's.current_candidate_id IS NOT NULL OR EXISTS ('
                   'SELECT 1 FROM report_candidates c WHERE c.plan_id = s.plan_id)) AND NOT EXISTS ('
                   "SELECT 1 FROM report_jobs j WHERE j.plan_id = s.plan_id AND j.status IN ('queued','running'))",
                   ordered)
    for row in cursor.fetchall():
        cursor.execute('INSERT INTO report_jobs (plan_id, created_by) VALUES (%s,%s)', (row['plan_id'], actor))


def request_recompute(plan_id, actor):
    with transaction() as cursor:
        ensure_slots(cursor)
        cursor.execute('SELECT 1 FROM comparison_plans WHERE id = %s', (plan_id,))
        if not cursor.fetchone():
            raise HTTPException(404, '未找到方案版本')
        cursor.execute("SELECT id, status FROM report_jobs WHERE plan_id = %s AND status IN ('queued','running') "
                       'ORDER BY id LIMIT 1', (plan_id,))
        job = cursor.fetchone()
        if not job:
            cursor.execute('INSERT INTO report_jobs (plan_id, created_by) VALUES (%s,%s)', (plan_id, actor))
            job = dict(id=cursor.lastrowid, status=JobStatus.QUEUED)
            record(cursor, actor, 'report.recompute', job['id'])
    wake_worker()
    return dict(job_id=job['id'], status=job['status'])


def retry_job(job_id, actor):
    with transaction() as cursor:
        cursor.execute('SELECT id, plan_id, status FROM report_jobs WHERE id = %s FOR UPDATE', (job_id,))
        job = cursor.fetchone()
        if not job:
            raise HTTPException(404, '未找到重算任务')
        if job['status'] != JobStatus.FAILED:
            raise HTTPException(409, '仅待补正的重算任务可重试')
        cursor.execute("SELECT 1 FROM report_jobs WHERE plan_id = %s AND status IN ('queued','running') LIMIT 1",
                       (job['plan_id'],))
        if cursor.fetchone():
            raise HTTPException(409, '该周报已有进行中的重算任务')
        cursor.execute("UPDATE report_jobs SET status = 'queued', failure = NULL, claim_token = NULL, "
                       'claimed_at = NULL, finished_at = NULL WHERE id = %s', (job_id,))
        record(cursor, actor, 'report.retry', job_id)
    wake_worker()
    return dict(job_id=job_id, status=JobStatus.QUEUED)


def compute_delta(before, snapshot_text, result):
    """对照上一版现值，交代哪些票进出或改过、构成差和系数差各变多少。"""
    old_rows = {row['code']: row for row in json.loads(before['snapshot'])['tickets']}
    new_rows = {row['code']: row for row in json.loads(snapshot_text)['tickets']}
    old_result = json.loads(before['result'])
    modified = []
    for code in sorted(set(old_rows) & set(new_rows)):
        old, new = old_rows[code], new_rows[code]
        if old['revision'] != new['revision']:
            changes = {key: [old[key], new[key]] for key in TICKET_FIELDS if old[key] != new[key]}
            modified.append(dict(code=code, from_revision=old['revision'], to_revision=new['revision'],
                                 changes=changes))
    metrics = {key: dict(before=old_result[key], after=result[key], change=result[key] - old_result[key])
               for key in METRIC_KEYS}
    return dict(before_candidate_id=before['id'],
                entered=sorted(set(new_rows) - set(old_rows)),
                exited=sorted(set(old_rows) - set(new_rows)),
                modified=modified, metrics=metrics)


def compute_job(job):
    job_id, plan_id, token = job['id'], job['plan_id'], job['token']
    prefixed = ', '.join(f'p.{column}' for column in PLAN_COLUMNS.split(', '))
    try:
        with transaction() as cursor:
            cursor.execute(f'SELECT s.sample_seq, s.current_candidate_id, {prefixed} FROM report_slots s '
                           'JOIN comparison_plans p ON p.id = s.plan_id WHERE s.plan_id = %s', (plan_id,))
            slot = cursor.fetchone()
            if not slot:
                raise AnalysisError('周报槽位不存在，请重新发起重算。')
            cursor.execute(f'SELECT {TICKET_COLUMNS} FROM tickets WHERE branch IN (%s,%s) '
                           'AND worked_on BETWEEN %s AND %s ORDER BY code',
                           (slot['focus_branch'], slot['control_branch'], slot['date_from'], slot['date_to']))
            rows = cursor.fetchall()
            before = None
            if slot['current_candidate_id']:
                cursor.execute('SELECT id, snapshot, result FROM report_candidates WHERE id = %s',
                               (slot['current_candidate_id'],))
                before = cursor.fetchone()
        plan = {column: slot[column] for column in PLAN_COLUMNS.split(', ')}
        text = canonical(dict(method=METHOD, plan=plan, tickets=rows))
        result = analyze(json.loads(text))
        delta = compute_delta(before, text, result) if before else None
        with transaction() as cursor:
            cursor.execute('SELECT sample_seq FROM report_slots WHERE plan_id = %s FOR UPDATE', (plan_id,))
            fresh = cursor.fetchone()
            status = (CandidateStatus.PENDING if fresh and fresh['sample_seq'] == slot['sample_seq']
                      else CandidateStatus.STALE)
            cursor.execute(
                'INSERT INTO report_candidates (plan_id, sample_seq, status, sample_count, snapshot, snapshot_sha, '
                'result, `delta`) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) AS incoming ON DUPLICATE KEY UPDATE '
                'id = LAST_INSERT_ID(id), '
                'status = IF(report_candidates.status = \'published\', report_candidates.status, incoming.status), '
                'sample_count = incoming.sample_count, '
                'snapshot = incoming.snapshot, snapshot_sha = incoming.snapshot_sha, result = incoming.result, '
                '`delta` = incoming.`delta`, computed_at = UTC_TIMESTAMP(6)',
                (plan_id, slot['sample_seq'], status, len(rows), text, checksum(text), canonical(result),
                 canonical(delta) if delta else None))
            candidate_id = cursor.lastrowid
            cursor.execute("UPDATE report_jobs SET status = 'done', candidate_id = %s, finished_at = UTC_TIMESTAMP(6) "
                           "WHERE id = %s AND claim_token = %s AND status = 'running'", (candidate_id, job_id, token))
            if not cursor.rowcount:
                raise ClaimLost()
            record(cursor, 'worker', 'report.done', job_id)
            if status == CandidateStatus.STALE:
                # 计算期间样本又有更新：候选稿出生即过期，补一个跟进任务收敛到最新样本。
                cursor.execute("SELECT 1 FROM report_jobs WHERE plan_id = %s AND status IN ('queued','running') "
                               'LIMIT 1', (plan_id,))
                if not cursor.fetchone():
                    cursor.execute('INSERT INTO report_jobs (plan_id, created_by) VALUES (%s,%s)',
                                   (plan_id, 'worker'))
                    follow_up = True
                else:
                    follow_up = False
        if status == CandidateStatus.STALE and follow_up:
            wake_worker()
        return
    except AnalysisError as exc:
        failure = str(exc)
    except ClaimLost:
        return
    except Exception:
        logger.exception('Report job %s failed', job_id)
        failure = '重算或候选稿保存中断，请重试。'
    with transaction() as cursor:
        cursor.execute("UPDATE report_jobs SET status = 'failed', failure = %s, finished_at = UTC_TIMESTAMP(6) "
                       "WHERE id = %s AND claim_token = %s AND status = 'running'", (failure, job_id, token))
        if cursor.rowcount:
            record(cursor, 'worker', 'report.failed', job_id)


def _metrics(row):
    result = json.loads(row['result'])
    return {key: result[key] for key in METRIC_KEYS}


def _summary(row):
    summary = {key: row[key] for key in CANDIDATE_COLUMNS.split(', ')}
    summary.update(_metrics(row))
    summary['delta'] = json.loads(row['delta']) if row['delta'] else None
    return summary


def _attention(slot, current, pending, job, history, staff):
    if job and job['status'] in (JobStatus.QUEUED, JobStatus.RUNNING):
        return 'recomputing'
    if pending:
        return 'awaiting_publish' if staff else 'recomputing'
    if job and job['status'] == JobStatus.FAILED:
        return 'failed'
    if not current:
        return 'vacant' if history else 'idle'
    if current['sample_seq'] < slot['sample_seq']:
        return 'outdated'
    return 'current'


def _slot_row(slot):
    return {key: slot[key] for key in
            ('plan_id', 'plan_key', 'version', 'label', 'focus_branch', 'control_branch', 'coefficient_ref',
             'date_from', 'date_to', 'min_samples', 'sample_seq', 'current_candidate_id')}


SLOT_SELECT = ('SELECT p.id AS plan_id, p.plan_key, p.version, p.label, p.focus_branch, p.control_branch, '
               'p.coefficient_ref, p.date_from, p.date_to, p.min_samples, s.sample_seq, s.current_candidate_id '
               'FROM report_slots s JOIN comparison_plans p ON p.id = s.plan_id')


def list_reports(role):
    staff = role != Role.OBSERVER
    with transaction() as cursor:
        ensure_slots(cursor)
        cursor.execute(f'{SLOT_SELECT} ORDER BY p.plan_key, p.version DESC, p.id')
        slots = cursor.fetchall()
        reports = []
        for slot in slots:
            current = None
            if slot['current_candidate_id']:
                cursor.execute(f'SELECT {CANDIDATE_COLUMNS}, result, `delta` FROM report_candidates WHERE id = %s',
                               (slot['current_candidate_id'],))
                row = cursor.fetchone()
                current = _summary(row) if row else None
            pending = []
            if staff:
                cursor.execute(f"SELECT {CANDIDATE_COLUMNS}, result, `delta` FROM report_candidates "
                               "WHERE plan_id = %s AND status = 'pending' ORDER BY id DESC", (slot['plan_id'],))
                pending = [_summary(row) for row in cursor.fetchall()]
            cursor.execute(f'SELECT {JOB_COLUMNS} FROM report_jobs WHERE plan_id = %s ORDER BY id DESC LIMIT 1',
                           (slot['plan_id'],))
            job = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) AS history FROM report_candidates "
                           "WHERE plan_id = %s AND status = 'published'", (slot['plan_id'],))
            history = cursor.fetchone()['history']
            entry = dict(_slot_row(slot), current=current, history=history,
                         attention=_attention(slot, current, pending, job, history, staff))
            if staff:
                entry['pending'] = pending
                entry['job'] = job
            reports.append(entry)
        return reports


def get_report(plan_id, role):
    staff = role != Role.OBSERVER
    with transaction() as cursor:
        ensure_slots(cursor)
        cursor.execute(f'{SLOT_SELECT} WHERE s.plan_id = %s', (plan_id,))
        slot = cursor.fetchone()
        if not slot:
            raise HTTPException(404, '未找到周报口径')
        current = None
        if slot['current_candidate_id']:
            cursor.execute(f'SELECT {CANDIDATE_COLUMNS}, result, `delta` FROM report_candidates WHERE id = %s',
                           (slot['current_candidate_id'],))
            row = cursor.fetchone()
            if row:
                current = dict(_summary(row), result=json.loads(row['result']))
        clause = '' if staff else "AND status = 'published'"
        cursor.execute(f'SELECT {CANDIDATE_COLUMNS}, result, `delta` FROM report_candidates '
                       f'WHERE plan_id = %s {clause} ORDER BY id DESC LIMIT 30', (plan_id,))
        candidates = [_summary(row) for row in cursor.fetchall()]
        cursor.execute(f'SELECT {JOB_COLUMNS} FROM report_jobs WHERE plan_id = %s ORDER BY id DESC LIMIT 10',
                       (plan_id,))
        recent = cursor.fetchall()
        jobs = recent if staff else []
        cursor.execute("SELECT COUNT(*) AS history FROM report_candidates "
                       "WHERE plan_id = %s AND status = 'published'", (plan_id,))
        history = cursor.fetchone()['history']
        pending = [item for item in candidates if item['status'] == CandidateStatus.PENDING]
        job = recent[0] if recent else None
        return dict(plan=_slot_row(slot), current=current, candidates=candidates, jobs=jobs, history=history,
                    attention=_attention(slot, current, pending, job, history, staff))


def get_candidate(candidate_id, role, with_snapshot=False):
    with transaction() as cursor:
        cursor.execute('SELECT * FROM report_candidates WHERE id = %s', (candidate_id,))
        row = cursor.fetchone()
    if not row or (role == Role.OBSERVER and row['status'] != CandidateStatus.PUBLISHED):
        raise HTTPException(404, '未找到可阅候选稿')
    snapshot = json.loads(row['snapshot'])
    detail = {key: row[key] for key in CANDIDATE_COLUMNS.split(', ')}
    detail['plan'] = snapshot['plan']
    detail['result'] = json.loads(row['result'])
    detail['delta'] = json.loads(row['delta']) if row['delta'] else None
    if with_snapshot:
        detail['snapshot'] = row['snapshot']
    return detail


def publish_candidate(candidate_id, actor):
    with transaction() as cursor:
        ensure_slots(cursor)
        cursor.execute('SELECT plan_id, sample_seq, current_candidate_id FROM report_slots '
                       'ORDER BY plan_id FOR UPDATE')
        slots = cursor.fetchall()
        cursor.execute(f'SELECT {CANDIDATE_COLUMNS}, snapshot FROM report_candidates WHERE id = %s FOR UPDATE',
                       (candidate_id,))
        candidate = cursor.fetchone()
        if not candidate:
            raise HTTPException(404, '候选稿不存在')
        if candidate['status'] == CandidateStatus.PUBLISHED:
            raise HTTPException(409, '该候选稿已发布为现值')
        if candidate['status'] != CandidateStatus.PENDING:
            raise HTTPException(409, '样本已有更新，此候选稿过期，请改用最新候选稿')
        slot = next((item for item in slots if item['plan_id'] == candidate['plan_id']), None)
        if not slot or slot['sample_seq'] != candidate['sample_seq']:
            raise HTTPException(409, '样本已有更新，此候选稿过期，请改用最新候选稿')
        own_codes = {row['code'] for row in json.loads(candidate['snapshot'])['tickets']}
        vacated = []
        for other in slots:
            if other['plan_id'] == candidate['plan_id'] or not other['current_candidate_id']:
                continue
            cursor.execute('SELECT c.snapshot, p.plan_key, p.version, p.focus_branch, p.control_branch, '
                           'p.date_from, p.date_to FROM report_candidates c '
                           'JOIN comparison_plans p ON p.id = c.plan_id WHERE c.id = %s',
                           (other['current_candidate_id'],))
            row = cursor.fetchone()
            shared = own_codes & {item['code'] for item in json.loads(row['snapshot'])['tickets']}
            if not shared:
                continue
            marks = ','.join(['%s'] * len(shared))
            cursor.execute(f'SELECT code FROM tickets WHERE code IN ({marks}) AND branch IN (%s,%s) '
                           'AND worked_on BETWEEN %s AND %s',
                           (*sorted(shared), row['focus_branch'], row['control_branch'],
                            row['date_from'], row['date_to']))
            moved = sorted(shared - {item['code'] for item in cursor.fetchall()})
            if not moved:
                continue
            cursor.execute('UPDATE report_slots SET current_candidate_id = NULL, updated_at = UTC_TIMESTAMP(6) '
                           'WHERE plan_id = %s', (other['plan_id'],))
            record(cursor, actor, 'report.vacate', f"{row['plan_key']}.v{row['version']}")
            vacated.append(dict(plan_id=other['plan_id'], plan_key=row['plan_key'],
                                version=row['version'], moved=moved))
        cursor.execute("UPDATE report_candidates SET status = 'published', published_at = UTC_TIMESTAMP(6), "
                       'published_by = %s WHERE id = %s', (actor, candidate_id))
        cursor.execute('UPDATE report_slots SET current_candidate_id = %s, updated_at = UTC_TIMESTAMP(6) '
                       'WHERE plan_id = %s', (candidate_id, candidate['plan_id']))
        record(cursor, actor, 'report.publish', candidate_id)
    return dict(id=candidate_id, status=CandidateStatus.PUBLISHED, vacated=vacated)
