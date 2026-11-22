import logging
import time
from pathlib import Path

from src.models.db import transaction

logger = logging.getLogger(__name__)
MIGRATIONS = Path(__file__).resolve().parents[2] / 'migrations'
ALREADY_EXISTS = (1050, 1061)  # table / key already exists
DUPLICATE_ENTRY = 1062


def _statements(text):
    return [statement.strip() for statement in text.split(';') if statement.strip()]


def migrate():
    with transaction() as cursor:
        cursor.execute('CREATE TABLE IF NOT EXISTS schema_migrations ('
                       'filename VARCHAR(64) PRIMARY KEY, '
                       'applied_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)) CHARACTER SET utf8mb4')
        cursor.execute('SELECT filename FROM schema_migrations')
        applied = {row['filename'] for row in cursor.fetchall()}
        for path in sorted(MIGRATIONS.glob('*.sql')):
            if path.name in applied:
                continue
            for statement in _statements(path.read_text(encoding='utf-8')):
                try:
                    cursor.execute(statement)
                except Exception as exc:
                    if exc.args and exc.args[0] in ALREADY_EXISTS:
                        continue
                    raise
            try:
                cursor.execute('INSERT INTO schema_migrations (filename) VALUES (%s)', (path.name,))
            except Exception as exc:
                if not (exc.args and exc.args[0] == DUPLICATE_ENTRY):
                    raise
            logger.info('Migration recorded: %s', path.name)


def migrate_with_retry(attempts=10, delay=2):
    for attempt in range(1, attempts + 1):
        try:
            migrate()
            return
        except Exception:
            if attempt == attempts:
                raise
            logger.warning('Migration attempt %s/%s failed, retrying', attempt, attempts, exc_info=True)
            time.sleep(delay)
