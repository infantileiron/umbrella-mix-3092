from fastapi import HTTPException
from pymysql.err import IntegrityError

from src.models.db import transaction
from src.models.queries import TICKET_COLUMNS
from src.services.audit import record
from src.services.reports import note_ticket_change
from src.utils.queue import wake_worker


def list_tickets(branch, page, size):
    where, args = ('WHERE branch=%s', (branch,)) if branch else ('', ())
    with transaction() as cursor:
        cursor.execute('SELECT branch, COUNT(*) AS tickets, AVG(minutes) AS mean_minutes '
                       'FROM tickets GROUP BY branch ORDER BY branch')
        branches = cursor.fetchall()
        cursor.execute(f'SELECT COUNT(*) AS total FROM tickets {where}', args)
        total = cursor.fetchone()['total']
        cursor.execute(f'SELECT {TICKET_COLUMNS} FROM tickets {where} '
                       'ORDER BY worked_on DESC, code LIMIT %s OFFSET %s', (*args, size, (page - 1) * size))
        items = cursor.fetchall()
    return dict(items=items, total=total, page=page, size=size, branches=branches)


def create_ticket(payload, actor):
    ticket = payload.model_dump()
    try:
        with transaction() as cursor:
            cursor.execute(f'INSERT INTO tickets ({TICKET_COLUMNS}) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1)',
                           (payload.code, *payload.model_dump(exclude={'code'}).values()))
            record(cursor, actor, 'ticket.create', payload.code)
            note_ticket_change(cursor, code=payload.code, revision=1, kind='create', actor=actor,
                               prev=None, new=ticket)
    except IntegrityError as exc:
        if exc.args[0] != 1062:
            raise
        raise HTTPException(409, '该工票编号已存在') from exc
    wake_worker()
    return {**ticket, 'revision': 1}


def edit_ticket(code, payload, actor):
    fields = payload.model_dump(exclude={'revision'})
    with transaction() as cursor:
        cursor.execute('SELECT branch, worked_on, revision FROM tickets WHERE code=%s FOR UPDATE', (code,))
        prev = cursor.fetchone()
        if not prev:
            raise HTTPException(404, '未找到该工票')
        if prev['revision'] != payload.revision:
            raise HTTPException(409, '工票已被修改，请刷新后重试')
        cursor.execute('UPDATE tickets SET branch=%s, worked_on=%s, ribs=%s, fabric=%s, mechanism=%s, '
                       'minutes=%s, note=%s, revision=revision+1 WHERE code=%s',
                       (*fields.values(), code))
        record(cursor, actor, 'ticket.edit', code)
        note_ticket_change(cursor, code=code, revision=payload.revision + 1, kind='edit', actor=actor,
                           prev=prev, new=fields)
    wake_worker()
    return dict(code=code, **fields, revision=payload.revision + 1)
