CREATE TABLE IF NOT EXISTS ticket_changes (
    seq BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(32) NOT NULL,
    revision INT UNSIGNED NOT NULL,
    kind ENUM('create','edit') NOT NULL,
    actor VARCHAR(32) NOT NULL,
    prev_branch ENUM('north','south'),
    prev_worked_on DATE,
    new_branch ENUM('north','south') NOT NULL,
    new_worked_on DATE NOT NULL,
    changed_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY ticket_revision (code, revision)
) CHARACTER SET utf8mb4;

CREATE TABLE IF NOT EXISTS report_slots (
    plan_id BIGINT UNSIGNED PRIMARY KEY,
    sample_seq BIGINT UNSIGNED NOT NULL DEFAULT 0,
    current_candidate_id BIGINT UNSIGNED,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    FOREIGN KEY (plan_id) REFERENCES comparison_plans (id)
) CHARACTER SET utf8mb4;

CREATE TABLE IF NOT EXISTS report_candidates (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    plan_id BIGINT UNSIGNED NOT NULL,
    sample_seq BIGINT UNSIGNED NOT NULL,
    status ENUM('pending','published','stale') NOT NULL DEFAULT 'pending',
    sample_count SMALLINT UNSIGNED NOT NULL,
    snapshot LONGTEXT NOT NULL,
    snapshot_sha CHAR(64) NOT NULL,
    result JSON NOT NULL,
    delta JSON,
    computed_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    published_at DATETIME(6),
    published_by VARCHAR(32),
    UNIQUE KEY plan_sample (plan_id, sample_seq),
    INDEX slot_status (plan_id, status),
    FOREIGN KEY (plan_id) REFERENCES comparison_plans (id)
) CHARACTER SET utf8mb4;

CREATE TABLE IF NOT EXISTS report_jobs (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    plan_id BIGINT UNSIGNED NOT NULL,
    status ENUM('queued','running','done','failed') NOT NULL DEFAULT 'queued',
    candidate_id BIGINT UNSIGNED,
    failure VARCHAR(240),
    attempts INT UNSIGNED NOT NULL DEFAULT 0,
    claim_token CHAR(32),
    claimed_at DATETIME(6),
    created_by VARCHAR(32) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    finished_at DATETIME(6),
    INDEX report_queue (status, id),
    INDEX report_plan (plan_id, status),
    FOREIGN KEY (plan_id) REFERENCES comparison_plans (id)
) CHARACTER SET utf8mb4;
