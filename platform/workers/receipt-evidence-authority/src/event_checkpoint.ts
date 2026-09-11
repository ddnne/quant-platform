import { canonicalDigest, isSha256 } from "./canonical";

// Bounded keyset page: tens of receipt operations per activation, not one
// row and not a full-history request scan. Daily prefix re-audit matches the
// low issuance rate of this authority; empty/idle DOs must not spin.
export const EVENT_AUDIT_PAGE_SIZE = 128;
export const EVENT_AUDIT_MAX_RETRIES = 5;
export const EVENT_AUDIT_INITIAL_BACKOFF_MS = 2_000;
export const EVENT_AUDIT_MAX_BACKOFF_MS = 60_000;
export const EVENT_AUDIT_PAGE_DELAY_MS = 1_000;
export const EVENT_AUDIT_PERIODIC_MS = 86_400_000;
export const EVENT_AUDIT_RETRY_COOLDOWN_MS = 3_600_000;

export type AuthorityEventRecord = {
  sequence: number;
  operation_id: string;
  event_type: string;
  payload_digest: string;
  prior_event_digest: string | null;
  event_digest: string;
  observed_at: string;
};

export type EventHead = {
  sequence: number;
  event_digest: string | null;
};

export type EventAuditIssuanceState = "HOLD" | "PERMITTED" | "FAILED";
export type EventAuditStatus =
  | "EMPTY_INITIALIZED"
  | "BOOTSTRAP_PENDING"
  | "IN_PROGRESS"
  | "AUDITED"
  | "RETRY_COOLDOWN"
  | "FAILED";

export type EventAuditProgress = {
  issuance_state: EventAuditIssuanceState;
  status: EventAuditStatus;
  pinned_target_sequence: number;
  pinned_target_digest: string | null;
  cursor_sequence: number;
  cursor_digest: string | null;
  audited_sequence: number;
  audited_digest: string | null;
  next_alarm_at: number | null;
  retry_count: number;
  failure_reason: string | null;
  last_error: string | null;
  last_audit_page_event_rows: number;
  last_audit_page_event_hashes: number;
  updated_at: string;
};

type EventWorkCounters = {
  rows: number;
  hashes: number;
};

const EVENT_SELECT =
  `sequence,operation_id,event_type,payload_digest,
   prior_event_digest,event_digest,observed_at`;

export function authorityEventCanonicalDocument(row: {
  sequence: number;
  operation_id: string;
  event_type: string;
  payload_digest: string;
  prior_event_digest: string | null;
  observed_at: string;
}): {
  schema_version: "receipt-authority-event/v1";
  sequence: number;
  operation_id: string;
  event_type: string;
  payload_digest: string;
  prior_event_digest: string | null;
  observed_at: string;
} {
  return {
    schema_version: "receipt-authority-event/v1",
    sequence: row.sequence,
    operation_id: row.operation_id,
    event_type: row.event_type,
    payload_digest: row.payload_digest,
    prior_event_digest: row.prior_event_digest,
    observed_at: row.observed_at,
  };
}

export function hashAuthorityEvent(
  row: {
    sequence: number;
    operation_id: string;
    event_type: string;
    payload_digest: string;
    prior_event_digest: string | null;
    observed_at: string;
  },
): Promise<string> {
  return canonicalDigest(authorityEventCanonicalDocument(row));
}

export function eventAuditBackoffMs(retryCount: number): number {
  const shift = Math.min(Math.max(retryCount, 0), 16);
  return Math.min(
    EVENT_AUDIT_INITIAL_BACKOFF_MS * (2 ** shift),
    EVENT_AUDIT_MAX_BACKOFF_MS,
  );
}

export function initializeEventCheckpoint(storage: DurableObjectStorage): void {
  storage.sql.exec(`
    CREATE TABLE IF NOT EXISTS authority_event_head (
      singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
      sequence INTEGER NOT NULL CHECK (sequence >= 0),
      event_digest TEXT,
      updated_at TEXT NOT NULL,
      CHECK (
        (sequence = 0 AND event_digest IS NULL)
        OR
        (sequence > 0 AND event_digest IS NOT NULL)
      )
    );
    CREATE TABLE IF NOT EXISTS authority_event_audit (
      singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
      issuance_state TEXT NOT NULL CHECK (
        issuance_state IN ('HOLD','PERMITTED','FAILED')
      ),
      status TEXT NOT NULL CHECK (
        status IN (
          'EMPTY_INITIALIZED','BOOTSTRAP_PENDING','IN_PROGRESS','AUDITED',
          'RETRY_COOLDOWN','FAILED'
        )
      ),
      pinned_target_sequence INTEGER NOT NULL CHECK (pinned_target_sequence >= 0),
      pinned_target_digest TEXT,
      cursor_sequence INTEGER NOT NULL CHECK (cursor_sequence >= 0),
      cursor_digest TEXT,
      audited_sequence INTEGER NOT NULL CHECK (audited_sequence >= 0),
      audited_digest TEXT,
      next_alarm_at INTEGER,
      retry_count INTEGER NOT NULL CHECK (retry_count >= 0),
      failure_reason TEXT,
      last_error TEXT,
      last_audit_page_event_rows INTEGER NOT NULL
        CHECK (last_audit_page_event_rows >= 0),
      last_audit_page_event_hashes INTEGER NOT NULL
        CHECK (last_audit_page_event_hashes >= 0),
      updated_at TEXT NOT NULL,
      CHECK (
        (pinned_target_sequence = 0 AND pinned_target_digest IS NULL)
        OR
        (pinned_target_sequence > 0 AND pinned_target_digest IS NOT NULL)
      ),
      CHECK (
        (cursor_sequence = 0 AND cursor_digest IS NULL)
        OR
        (cursor_sequence > 0 AND cursor_digest IS NOT NULL)
      ),
      CHECK (cursor_sequence <= pinned_target_sequence),
      CHECK (
        (audited_sequence = 0 AND audited_digest IS NULL)
        OR
        (audited_sequence > 0 AND audited_digest IS NOT NULL)
      ),
      CHECK (
        (
          issuance_state = 'HOLD'
          AND status IN ('BOOTSTRAP_PENDING','IN_PROGRESS','RETRY_COOLDOWN')
        )
        OR (
          issuance_state = 'PERMITTED'
          AND status IN (
            'EMPTY_INITIALIZED','AUDITED','IN_PROGRESS','RETRY_COOLDOWN'
          )
        )
        OR (
          issuance_state = 'FAILED'
          AND status = 'FAILED'
          AND failure_reason IS NOT NULL
        )
      )
    );
  `);
  const existing = readAuditProgress(storage);
  if (existing !== null) return;
  const now = new Date().toISOString();
  const tail = readEventTail(storage);
  if (tail.sequence === 0) {
    storage.sql.exec(
      `INSERT INTO authority_event_head
       (singleton,sequence,event_digest,updated_at) VALUES (1,0,NULL,?)`,
      now,
    );
    storage.sql.exec(
      `INSERT INTO authority_event_audit
       (singleton,issuance_state,status,pinned_target_sequence,pinned_target_digest,
        cursor_sequence,cursor_digest,audited_sequence,audited_digest,next_alarm_at,
        retry_count,failure_reason,last_error,last_audit_page_event_rows,
        last_audit_page_event_hashes,updated_at)
       VALUES (1,'PERMITTED','EMPTY_INITIALIZED',0,NULL,0,NULL,0,NULL,?,0,NULL,NULL,0,0,?)`,
      Date.now() + EVENT_AUDIT_PERIODIC_MS,
      now,
    );
    return;
  }
  storage.sql.exec(
    `INSERT INTO authority_event_audit
     (singleton,issuance_state,status,pinned_target_sequence,pinned_target_digest,
      cursor_sequence,cursor_digest,audited_sequence,audited_digest,next_alarm_at,
      retry_count,failure_reason,last_error,last_audit_page_event_rows,
      last_audit_page_event_hashes,updated_at)
     VALUES (1,'HOLD','BOOTSTRAP_PENDING',?,?,0,NULL,0,NULL,?,0,NULL,NULL,0,0,?)`,
    tail.sequence,
    tail.event_digest,
    Date.now(),
    now,
  );
}

export function readEventHead(storage: DurableObjectStorage): EventHead | null {
  const row = storage.sql.exec<{
    sequence: number;
    event_digest: string | null;
  }>(
    "SELECT sequence,event_digest FROM authority_event_head WHERE singleton=1",
  ).toArray()[0];
  return row ?? null;
}

export function readEventTail(storage: DurableObjectStorage): EventHead {
  const row = storage.sql.exec<{
    sequence: number;
    event_digest: string | null;
  }>(
    "SELECT sequence,event_digest FROM authority_events ORDER BY sequence DESC LIMIT 1",
  ).toArray()[0];
  return row ?? { sequence: 0, event_digest: null };
}

export function readAuditProgress(
  storage: DurableObjectStorage,
): EventAuditProgress | null {
  return storage.sql.exec<EventAuditProgress>(
    `SELECT issuance_state,status,pinned_target_sequence,pinned_target_digest,
            cursor_sequence,cursor_digest,audited_sequence,audited_digest,
            next_alarm_at,retry_count,failure_reason,last_error,
            last_audit_page_event_rows,last_audit_page_event_hashes,updated_at
       FROM authority_event_audit WHERE singleton=1`,
  ).toArray()[0] ?? null;
}

export function requireIssuanceEligible(progress: EventAuditProgress | null): void {
  if (progress === null) {
    throw new Error("receipt authority event checkpoint is absent");
  }
  if (progress.issuance_state === "FAILED") {
    throw new Error(
      "receipt authority issuance is closed after event-chain integrity failure",
    );
  }
  if (progress.issuance_state === "HOLD") {
    throw new Error(
      "receipt authority issuance is held for event-chain bootstrap",
    );
  }
}

export function writeEventHead(
  storage: DurableObjectStorage,
  head: EventHead,
  updatedAt: string,
): void {
  storage.sql.exec(
    `INSERT INTO authority_event_head (singleton,sequence,event_digest,updated_at)
     VALUES (1,?,?,?)
     ON CONFLICT(singleton) DO UPDATE SET
       sequence=excluded.sequence,
       event_digest=excluded.event_digest,
       updated_at=excluded.updated_at`,
    head.sequence,
    head.event_digest,
    updatedAt,
  );
}

export function writeIntegrityFailure(
  storage: DurableObjectStorage,
  reason: string,
  updatedAt: string,
): void {
  const current = readAuditProgress(storage);
  if (current === null) {
    storage.sql.exec(
      `INSERT INTO authority_event_audit
       (singleton,issuance_state,status,pinned_target_sequence,pinned_target_digest,
        cursor_sequence,cursor_digest,audited_sequence,audited_digest,next_alarm_at,
        retry_count,failure_reason,last_error,last_audit_page_event_rows,
        last_audit_page_event_hashes,updated_at)
       VALUES (1,'FAILED','FAILED',0,NULL,0,NULL,0,NULL,NULL,?,?,NULL,0,0,?)`,
      EVENT_AUDIT_MAX_RETRIES,
      reason,
      updatedAt,
    );
    return;
  }
  if (current.issuance_state === "FAILED") return;
  storage.sql.exec(
    `UPDATE authority_event_audit
        SET issuance_state='FAILED',status='FAILED',failure_reason=?,
            next_alarm_at=NULL,retry_count=?,last_error=NULL,updated_at=?
      WHERE singleton=1 AND issuance_state != 'FAILED'`,
    reason,
    EVENT_AUDIT_MAX_RETRIES,
    updatedAt,
  );
}

export function persistIntegrityFailure(
  storage: DurableObjectStorage,
  reason: string,
): void {
  storage.transactionSync(() => {
    writeIntegrityFailure(storage, reason, new Date().toISOString());
  });
}

export function loadAuditPage(
  storage: DurableObjectStorage,
  progress: EventAuditProgress,
): AuthorityEventRecord[] {
  const rows = storage.sql.exec<AuthorityEventRecord>(
    `SELECT ${EVENT_SELECT}
       FROM authority_events
      WHERE sequence > ? AND sequence <= ?
      ORDER BY sequence
      LIMIT ?`,
    progress.cursor_sequence,
    progress.pinned_target_sequence,
    EVENT_AUDIT_PAGE_SIZE,
  ).toArray();
  return rows;
}

export async function validateAuditPage(
  rows: readonly AuthorityEventRecord[],
  progress: EventAuditProgress,
): Promise<
  | { ok: true; cursor: EventHead; hashes: number }
  | { ok: false; reason: string; hashes: number }
> {
  if (
    progress.pinned_target_sequence > 0 &&
    (progress.pinned_target_digest === null ||
      !isSha256(progress.pinned_target_digest))
  ) {
    return {
      ok: false,
      reason: "receipt authority event chain is corrupt",
      hashes: 0,
    };
  }
  if (rows.length === 0) {
    if (progress.cursor_sequence < progress.pinned_target_sequence) {
      return {
        ok: false,
        reason: "receipt authority event chain is corrupt",
        hashes: 0,
      };
    }
    if (
      progress.cursor_sequence === progress.pinned_target_sequence &&
      progress.cursor_digest !== progress.pinned_target_digest
    ) {
      return {
        ok: false,
        reason: "receipt authority event chain is corrupt",
        hashes: 0,
      };
    }
    return {
      ok: true,
      cursor: {
        sequence: progress.cursor_sequence,
        event_digest: progress.cursor_digest,
      },
      hashes: 0,
    };
  }
  let expectedSequence = progress.cursor_sequence + 1;
  let prior = progress.cursor_digest;
  let hashes = 0;
  for (const row of rows) {
    hashes += 1;
    if (
      row.sequence !== expectedSequence ||
      row.sequence > progress.pinned_target_sequence ||
      row.prior_event_digest !== prior ||
      !isSha256(row.operation_id) ||
      !isSha256(row.payload_digest) ||
      row.event_digest !== await hashAuthorityEvent(row)
    ) {
      return {
        ok: false,
        reason: "receipt authority event chain is corrupt",
        hashes,
      };
    }
    if (
      row.sequence === progress.pinned_target_sequence &&
      row.event_digest !== progress.pinned_target_digest
    ) {
      return {
        ok: false,
        reason: "receipt authority event chain is corrupt",
        hashes,
      };
    }
    prior = row.event_digest;
    expectedSequence += 1;
  }
  const cursor = rows[rows.length - 1]!;
  return {
    ok: true,
    cursor: { sequence: cursor.sequence, event_digest: cursor.event_digest },
    hashes,
  };
}

function alarmIsDue(progress: EventAuditProgress, now: number): boolean {
  return progress.next_alarm_at === null || progress.next_alarm_at <= now;
}

function pinIdleAuditTarget(
  storage: DurableObjectStorage,
  now: number,
  nowIso: string,
): EventAuditProgress | null {
  const progress = readAuditProgress(storage);
  if (progress === null || progress.issuance_state === "FAILED") return progress;
  if (progress.status === "RETRY_COOLDOWN") {
    if (!alarmIsDue(progress, now)) return progress;
    storage.sql.exec(
      `UPDATE authority_event_audit
          SET status='IN_PROGRESS',retry_count=0,last_error=NULL,
              next_alarm_at=?,updated_at=?
        WHERE singleton=1 AND status='RETRY_COOLDOWN'`,
      now,
      nowIso,
    );
    return readAuditProgress(storage);
  }
  if (progress.status === "BOOTSTRAP_PENDING") {
    if (!alarmIsDue(progress, now)) return progress;
    storage.sql.exec(
      `UPDATE authority_event_audit
          SET status='IN_PROGRESS',next_alarm_at=?,updated_at=?
        WHERE singleton=1 AND status='BOOTSTRAP_PENDING'`,
      now,
      nowIso,
    );
    return readAuditProgress(storage);
  }
  if (
    (progress.status === "AUDITED" || progress.status === "EMPTY_INITIALIZED") &&
    alarmIsDue(progress, now)
  ) {
    const tail = readEventTail(storage);
    if (tail.sequence === 0) return progress;
    storage.sql.exec(
      `UPDATE authority_event_audit
          SET status='IN_PROGRESS',pinned_target_sequence=?,pinned_target_digest=?,
              cursor_sequence=0,cursor_digest=NULL,next_alarm_at=?,retry_count=0,
              last_error=NULL,updated_at=?
        WHERE singleton=1 AND status IN ('AUDITED','EMPTY_INITIALIZED')`,
      tail.sequence,
      tail.event_digest,
      now,
      nowIso,
    );
    return readAuditProgress(storage);
  }
  return progress;
}

function advanceIdleSchedule(
  storage: DurableObjectStorage,
  now: number,
  nowIso: string,
): void {
  storage.sql.exec(
    `UPDATE authority_event_audit
        SET next_alarm_at=?,updated_at=?
      WHERE singleton=1 AND status IN ('EMPTY_INITIALIZED','AUDITED')`,
    now + EVENT_AUDIT_PERIODIC_MS,
    nowIso,
  );
}

function commitAuditPage(
  storage: DurableObjectStorage,
  expected: EventAuditProgress,
  cursor: EventHead,
  pageWork: EventWorkCounters,
  now: number,
  nowIso: string,
): boolean {
  return storage.transactionSync(() => {
    const current = readAuditProgress(storage);
    if (
      current === null ||
      current.issuance_state === "FAILED" ||
      current.pinned_target_sequence !== expected.pinned_target_sequence ||
      current.pinned_target_digest !== expected.pinned_target_digest ||
      current.cursor_sequence !== expected.cursor_sequence ||
      current.cursor_digest !== expected.cursor_digest
    ) return false;
    if (cursor.sequence === current.pinned_target_sequence) {
      if (cursor.event_digest !== current.pinned_target_digest) {
        writeIntegrityFailure(
          storage,
          "receipt authority event chain is corrupt",
          nowIso,
        );
        return true;
      }
      if (current.issuance_state === "HOLD") {
        const tail = readEventTail(storage);
        if (
          tail.sequence !== current.pinned_target_sequence ||
          tail.event_digest !== current.pinned_target_digest
        ) {
          writeIntegrityFailure(
            storage,
            "receipt authority event chain is corrupt",
            nowIso,
          );
          return true;
        }
        writeEventHead(storage, tail, nowIso);
      }
      const issuanceState = current.issuance_state === "HOLD"
        ? "PERMITTED"
        : current.issuance_state;
      storage.sql.exec(
        `UPDATE authority_event_audit
            SET issuance_state=?,status='AUDITED',cursor_sequence=?,cursor_digest=?,
                audited_sequence=?,audited_digest=?,next_alarm_at=?,retry_count=0,
                last_error=NULL,last_audit_page_event_rows=?,
                last_audit_page_event_hashes=?,updated_at=?
          WHERE singleton=1`,
        issuanceState,
        cursor.sequence,
        cursor.event_digest,
        current.pinned_target_sequence,
        current.pinned_target_digest,
        now + EVENT_AUDIT_PERIODIC_MS,
        pageWork.rows,
        pageWork.hashes,
        nowIso,
      );
      return true;
    }
    storage.sql.exec(
      `UPDATE authority_event_audit
          SET status='IN_PROGRESS',cursor_sequence=?,cursor_digest=?,
              next_alarm_at=?,retry_count=0,last_error=NULL,
              last_audit_page_event_rows=?,last_audit_page_event_hashes=?,
              updated_at=?
        WHERE singleton=1`,
      cursor.sequence,
      cursor.event_digest,
      now + EVENT_AUDIT_PAGE_DELAY_MS,
      pageWork.rows,
      pageWork.hashes,
      nowIso,
    );
    return true;
  });
}

function scheduleAuditRetry(
  storage: DurableObjectStorage,
  now: number,
  nowIso: string,
  lastError: string,
): void {
  const current = readAuditProgress(storage);
  if (current === null || current.issuance_state === "FAILED") return;
  const retryCount = current.retry_count + 1;
  if (retryCount >= EVENT_AUDIT_MAX_RETRIES) {
    storage.sql.exec(
      `UPDATE authority_event_audit
          SET status='RETRY_COOLDOWN',retry_count=0,next_alarm_at=?,
              last_error=?,updated_at=?
        WHERE singleton=1 AND issuance_state != 'FAILED'`,
      now + EVENT_AUDIT_RETRY_COOLDOWN_MS,
      lastError,
      nowIso,
    );
    return;
  }
  storage.sql.exec(
    `UPDATE authority_event_audit
        SET retry_count=?,next_alarm_at=?,last_error=?,updated_at=?
      WHERE singleton=1 AND issuance_state != 'FAILED'`,
    retryCount,
    now + eventAuditBackoffMs(retryCount),
    lastError,
    nowIso,
  );
}

export function intendedEventAuditAlarmAt(
  storage: DurableObjectStorage,
  now: number,
): number | null {
  const progress = readAuditProgress(storage);
  if (progress === null || progress.issuance_state === "FAILED") return null;
  const intended = progress.next_alarm_at ?? now;
  if (
    progress.issuance_state === "HOLD" ||
    progress.status === "BOOTSTRAP_PENDING" ||
    progress.status === "IN_PROGRESS" ||
    progress.status === "RETRY_COOLDOWN"
  ) {
    return intended <= now ? now : intended;
  }
  if (intended <= now) return now;
  return intended;
}

export async function repairEventAuditAlarm(
  storage: DurableObjectStorage,
): Promise<void> {
  const now = Date.now();
  const intended = intendedEventAuditAlarmAt(storage, now);
  const scheduled = await storage.getAlarm();
  if (intended === null) {
    if (scheduled !== null) await storage.deleteAlarm();
    return;
  }
  if (scheduled === null) {
    await storage.setAlarm(intended);
    return;
  }
  if (scheduled > intended) await storage.setAlarm(intended);
}

export async function runBoundedEventAudit(
  storage: DurableObjectStorage,
): Promise<void> {
  const now = Date.now();
  const nowIso = new Date(now).toISOString();
  try {
    const pinned = storage.transactionSync(() =>
      pinIdleAuditTarget(storage, now, nowIso)
    );
    if (pinned === null || pinned.issuance_state === "FAILED") {
      await repairEventAuditAlarm(storage);
      return;
    }
    if (!alarmIsDue(pinned, now)) {
      await repairEventAuditAlarm(storage);
      return;
    }
    if (
      pinned.status === "EMPTY_INITIALIZED" ||
      pinned.status === "AUDITED" ||
      pinned.status === "RETRY_COOLDOWN"
    ) {
      if (
        pinned.status === "EMPTY_INITIALIZED" ||
        pinned.status === "AUDITED"
      ) {
        advanceIdleSchedule(storage, now, nowIso);
      }
      await repairEventAuditAlarm(storage);
      return;
    }
    if (pinned.cursor_sequence > pinned.pinned_target_sequence) {
      persistIntegrityFailure(storage, "receipt authority event chain is corrupt");
      await repairEventAuditAlarm(storage);
      return;
    }
    if (pinned.cursor_sequence === pinned.pinned_target_sequence) {
      if (pinned.cursor_digest !== pinned.pinned_target_digest) {
        persistIntegrityFailure(
          storage,
          "receipt authority event chain is corrupt",
        );
      } else {
        commitAuditPage(
          storage,
          pinned,
          {
            sequence: pinned.cursor_sequence,
            event_digest: pinned.cursor_digest,
          },
          { rows: 0, hashes: 0 },
          now,
          nowIso,
        );
      }
      await repairEventAuditAlarm(storage);
      return;
    }
    const page = loadAuditPage(storage, pinned);
    const validated = await validateAuditPage(page, pinned);
    const afterReplay = readAuditProgress(storage);
    if (afterReplay?.issuance_state === "FAILED") {
      await repairEventAuditAlarm(storage);
      return;
    }
    if (!validated.ok) {
      persistIntegrityFailure(storage, validated.reason);
      await repairEventAuditAlarm(storage);
      return;
    }
    const committed = commitAuditPage(
      storage,
      pinned,
      validated.cursor,
      { rows: page.length, hashes: validated.hashes },
      now,
      nowIso,
    );
    if (!committed) {
      scheduleAuditRetry(
        storage,
        Date.now(),
        new Date().toISOString(),
        "receipt authority event audit progress raced",
      );
    }
    await repairEventAuditAlarm(storage);
  } catch (error) {
    const progress = readAuditProgress(storage);
    if (progress?.issuance_state !== "FAILED") {
      const message = error instanceof Error
        ? error.message
        : "receipt authority event audit failed";
      scheduleAuditRetry(
        storage,
        Date.now(),
        new Date().toISOString(),
        message,
      );
    }
    await repairEventAuditAlarm(storage);
  }
}
