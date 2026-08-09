//! Durable SQLite task state for the Barq download engine.
//!
//! This crate owns task metadata and its state-machine only. It never opens a
//! network connection or touches a destination file. `Completed` means that a
//! caller recorded a representation, durably finalized the destination itself,
//! and then explicitly confirmed that finalization here.

use std::path::{Path, PathBuf};

use engine_core::{FileIdentity, TaskState};
use sqlite::{Connection, Row, Value};
use thiserror::Error;

/// The newest migration understood by this binary.
pub const SCHEMA_VERSION: u32 = 2;
const BUSY_TIMEOUT_MS: usize = 5_000;

#[derive(Error, Debug)]
pub enum StateStoreError {
    #[error("database error: {0}")]
    Sqlite(#[from] sqlite::Error),
    #[error("database schema version {found} is newer than supported version {supported}")]
    UnsupportedSchema { found: u32, supported: u32 },
    #[error("task already exists: {0}")]
    TaskAlreadyExists(String),
    #[error("task ID has been retired and cannot be reused: {0}")]
    TaskIdRetired(String),
    #[error("task not found: {0}")]
    TaskNotFound(String),
    #[error("invalid task record: {0}")]
    InvalidTaskRecord(&'static str),
    #[error("invalid state transition from {from:?} to {to:?}")]
    InvalidStateTransition { from: TaskState, to: TaskState },
    #[error("task is not downloading: {task_id} is {state:?}")]
    TaskNotDownloading { task_id: String, state: TaskState },
    #[error(
        "download attempt ownership was lost for {task_id}: expected generation {expected}, current generation {actual}"
    )]
    AttemptOwnershipLost {
        task_id: String,
        expected: u64,
        actual: u64,
    },
    #[error("task version conflict for {task_id}: expected {expected}, current {actual}")]
    VersionConflict {
        task_id: String,
        expected: u64,
        actual: u64,
    },
    #[error("download progress cannot move backwards for {task_id}: current {current}, attempted {attempted}")]
    ProgressRegression {
        task_id: String,
        current: u64,
        attempted: u64,
    },
    #[error("transfer metadata is immutable once observed for task: {0}")]
    MetadataImmutable(String),
    #[error("finalization has already been confirmed for task: {0}")]
    FinalizationAlreadyConfirmed(String),
    #[error("task cannot be finalized yet: {0}")]
    FinalizationNotReady(String),
    #[error("task cannot complete until metadata and durable finalization are recorded: {0}")]
    CompletionNotReady(String),
    #[error("active task cannot be deleted: {0}")]
    ActiveTaskCannotBeDeleted(String),
    #[error("task data is out of SQLite INTEGER range: {0}")]
    IntegerOutOfRange(&'static str),
    #[error("stored task data is corrupt: {0}")]
    CorruptRecord(String),
    #[error("task was modified by another writer: {0}")]
    ConcurrentModification(String),
}

/// Typed, durable representation of a download task.
///
/// `generation` is the ownership token for one active `Downloading` attempt.
/// `version` is incremented by every mutation and prevents stale writes within
/// the same attempt. Browser credentials and request secrets are deliberately
/// excluded from persistent state.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TaskRecord {
    pub id: String,
    pub url: String,
    pub destination: String,
    pub file_size: u64,
    pub downloaded_bytes: u64,
    pub identity: FileIdentity,
    pub metadata_observed: bool,
    pub finalization_confirmed: bool,
    pub generation: u64,
    pub version: u64,
    pub state: TaskState,
}

/// Capability for exactly one active `Downloading` attempt.
///
/// It is derived from a `TaskRecord` returned by the store and must accompany
/// every progress or finalization mutation for that attempt.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DownloadAttempt {
    generation: u64,
    version: u64,
}

/// A durable progress checkpoint for a single owned attempt.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TransferCheckpoint {
    pub attempt: DownloadAttempt,
    pub file_size: u64,
    pub downloaded_bytes: u64,
    pub identity: FileIdentity,
}

impl TransferCheckpoint {
    pub fn new(
        attempt: DownloadAttempt,
        file_size: u64,
        downloaded_bytes: u64,
        identity: FileIdentity,
    ) -> Self {
        Self {
            attempt,
            file_size,
            downloaded_bytes,
            identity,
        }
    }
}

impl TaskRecord {
    pub fn new(
        id: impl Into<String>,
        url: impl Into<String>,
        destination: impl Into<String>,
    ) -> Self {
        Self {
            id: id.into(),
            url: url.into(),
            destination: destination.into(),
            file_size: 0,
            downloaded_bytes: 0,
            identity: FileIdentity::default(),
            metadata_observed: false,
            finalization_confirmed: false,
            generation: 0,
            version: 0,
            state: TaskState::Pending,
        }
    }

    pub fn download_attempt(&self) -> Option<DownloadAttempt> {
        matches!(self.state, TaskState::Downloading).then_some(DownloadAttempt {
            generation: self.generation,
            version: self.version,
        })
    }
}

/// A single SQLite connection with a schema owned by the engine.
///
/// The connection uses WAL, foreign keys, a bounded busy timeout, and SQLite
/// `synchronous=FULL` for critical state commits. This protects database state;
/// it does not make destination-file writes durable by itself.
pub struct StateStore {
    database_path: PathBuf,
    connection: Connection,
}

impl StateStore {
    /// Opens (or creates) the task database at an explicit filesystem path.
    pub fn open(path: impl AsRef<Path>) -> Result<Self, StateStoreError> {
        let database_path = path.as_ref().to_path_buf();
        if database_path.as_os_str().is_empty() {
            return Err(StateStoreError::InvalidTaskRecord(
                "database path must not be empty",
            ));
        }

        let mut connection = sqlite::open(&database_path)?;
        connection.set_busy_timeout(BUSY_TIMEOUT_MS)?;
        connection.execute("PRAGMA foreign_keys = ON;")?;
        connection.execute("PRAGMA journal_mode = WAL;")?;
        connection.execute("PRAGMA synchronous = FULL;")?;

        let store = Self {
            database_path,
            connection,
        };
        store.migrate()?;
        Ok(store)
    }

    pub fn database_path(&self) -> &Path {
        &self.database_path
    }

    pub fn schema_version(&self) -> Result<u32, StateStoreError> {
        let statement = self
            .connection
            .prepare("SELECT COALESCE(MAX(version), 0) FROM schema_migrations;")?;
        let mut rows = statement.into_iter();
        let row = rows
            .next()
            .transpose()?
            .ok_or_else(|| StateStoreError::CorruptRecord("missing schema version".to_string()))?;
        let version: i64 = row.try_read(0)?;
        u32::try_from(version)
            .map_err(|_| StateStoreError::CorruptRecord("invalid schema version".to_string()))
    }

    /// Returns the current connection's journal mode for diagnostics and tests.
    pub fn journal_mode(&self) -> Result<String, StateStoreError> {
        let statement = self.connection.prepare("PRAGMA journal_mode;")?;
        let mut rows = statement.into_iter();
        let mut row = rows
            .next()
            .transpose()?
            .ok_or_else(|| StateStoreError::CorruptRecord("missing journal mode".to_string()))?;
        String::try_from(row.take(0)).map_err(StateStoreError::from)
    }

    /// Creates a fresh pending task without a transfer representation.
    ///
    /// A task ID is never reusable after deletion. This avoids an ABA bug where
    /// a stale downloader could accidentally write into a different task with
    /// the same caller-provided ID.
    pub fn create_task(&self, task: &TaskRecord) -> Result<(), StateStoreError> {
        validate_new_task(task)?;

        self.in_immediate_transaction(|store| {
            if store.get_task(&task.id)?.is_some() {
                return Err(StateStoreError::TaskAlreadyExists(task.id.clone()));
            }
            if store.is_task_id_retired(&task.id)? {
                return Err(StateStoreError::TaskIdRetired(task.id.clone()));
            }

            let mut statement = store.connection.prepare(
                "INSERT INTO tasks (
                    id, url, destination, file_size, downloaded_bytes,
                    etag, last_modified, supports_range, state, failure_message,
                    generation, version, metadata_observed, finalization_confirmed
                ) VALUES (?, ?, ?, 0, 0, NULL, NULL, 0, 'pending', NULL, 0, 0, 0, 0);",
            )?;
            statement.bind((1, task.id.as_str()))?;
            statement.bind((2, task.url.as_str()))?;
            statement.bind((3, task.destination.as_str()))?;
            statement.next()?;
            Ok(())
        })
    }

    pub fn get_task(&self, task_id: &str) -> Result<Option<TaskRecord>, StateStoreError> {
        let mut statement = self.connection.prepare(
            "SELECT id, url, destination, file_size, downloaded_bytes,
                    etag, last_modified, supports_range, state, failure_message,
                    generation, version, metadata_observed, finalization_confirmed
             FROM tasks
             WHERE id = ?;",
        )?;
        statement.bind((1, task_id))?;
        let mut rows = statement.into_iter();
        match rows.next() {
            Some(row) => task_from_row(row?).map(Some),
            None => Ok(None),
        }
    }

    pub fn list_tasks(&self) -> Result<Vec<TaskRecord>, StateStoreError> {
        let statement = self.connection.prepare(
            "SELECT id, url, destination, file_size, downloaded_bytes,
                    etag, last_modified, supports_range, state, failure_message,
                    generation, version, metadata_observed, finalization_confirmed
             FROM tasks
             ORDER BY created_at ASC, id ASC;",
        )?;
        statement
            .into_iter()
            .map(|row| task_from_row(row?))
            .collect()
    }

    /// Records durable byte progress for the currently owned download attempt.
    ///
    /// The caller must pass the generation and version returned by the store.
    /// The initial observation freezes `file_size` and `identity`; later calls
    /// must use the exact same metadata and may only advance progress.
    pub fn update_transfer_state(
        &self,
        task_id: &str,
        checkpoint: &TransferCheckpoint,
    ) -> Result<TaskRecord, StateStoreError> {
        validate_transfer_observation(
            checkpoint.file_size,
            checkpoint.downloaded_bytes,
            &checkpoint.identity,
        )?;

        self.in_immediate_transaction(|store| {
            let current = store.require_task(task_id)?;
            require_downloading_attempt(&current, task_id, checkpoint.attempt)?;
            if current.finalization_confirmed {
                return Err(StateStoreError::FinalizationAlreadyConfirmed(
                    task_id.to_string(),
                ));
            }
            if checkpoint.downloaded_bytes < current.downloaded_bytes {
                return Err(StateStoreError::ProgressRegression {
                    task_id: task_id.to_string(),
                    current: current.downloaded_bytes,
                    attempted: checkpoint.downloaded_bytes,
                });
            }
            if current.metadata_observed
                && (current.file_size != checkpoint.file_size
                    || current.identity != checkpoint.identity)
            {
                return Err(StateStoreError::MetadataImmutable(task_id.to_string()));
            }

            let next_version = next_counter(current.version, "version")?;
            let mut statement = store.connection.prepare(
                "UPDATE tasks
                 SET file_size = ?, downloaded_bytes = ?, etag = ?, last_modified = ?,
                     supports_range = ?, metadata_observed = 1, version = ?,
                     updated_at = CAST(strftime('%s', 'now') AS INTEGER)
                 WHERE id = ? AND state = 'downloading' AND generation = ? AND version = ?;",
            )?;
            statement.bind((1, to_sqlite_integer(checkpoint.file_size, "file_size")?))?;
            statement.bind((
                2,
                to_sqlite_integer(checkpoint.downloaded_bytes, "downloaded_bytes")?,
            ))?;
            statement.bind((3, Value::from(checkpoint.identity.etag.clone())))?;
            statement.bind((4, Value::from(checkpoint.identity.last_modified.clone())))?;
            statement.bind((5, bool_to_sqlite(checkpoint.identity.supports_range)))?;
            statement.bind((6, to_sqlite_integer(next_version, "version")?))?;
            statement.bind((7, task_id))?;
            statement.bind((
                8,
                to_sqlite_integer(checkpoint.attempt.generation, "generation")?,
            ))?;
            statement.bind((9, to_sqlite_integer(checkpoint.attempt.version, "version")?))?;
            statement.next()?;

            if store.connection.change_count() != 1 {
                return Err(StateStoreError::ConcurrentModification(task_id.to_string()));
            }
            store.require_task(task_id)
        })
    }

    /// Records that the caller has completed its own durable file finalization.
    ///
    /// The store deliberately cannot inspect or sync a destination path, so this
    /// is an explicit, versioned hand-off from the file-writer layer.
    pub fn confirm_finalization(
        &self,
        task_id: &str,
        attempt: DownloadAttempt,
    ) -> Result<TaskRecord, StateStoreError> {
        self.in_immediate_transaction(|store| {
            let current = store.require_task(task_id)?;
            require_downloading_attempt(&current, task_id, attempt)?;
            if current.finalization_confirmed {
                return Err(StateStoreError::FinalizationAlreadyConfirmed(
                    task_id.to_string(),
                ));
            }
            if !current.metadata_observed || current.downloaded_bytes != current.file_size {
                return Err(StateStoreError::FinalizationNotReady(task_id.to_string()));
            }

            let next_version = next_counter(current.version, "version")?;
            let mut statement = store.connection.prepare(
                "UPDATE tasks
                 SET finalization_confirmed = 1, version = ?,
                     updated_at = CAST(strftime('%s', 'now') AS INTEGER)
                 WHERE id = ? AND state = 'downloading' AND generation = ? AND version = ?;",
            )?;
            statement.bind((1, to_sqlite_integer(next_version, "version")?))?;
            statement.bind((2, task_id))?;
            statement.bind((3, to_sqlite_integer(attempt.generation, "generation")?))?;
            statement.bind((4, to_sqlite_integer(attempt.version, "version")?))?;
            statement.next()?;

            if store.connection.change_count() != 1 {
                return Err(StateStoreError::ConcurrentModification(task_id.to_string()));
            }
            store.require_task(task_id)
        })
    }

    /// Performs a versioned, validated state transition in one SQLite transaction.
    pub fn transition_task(
        &self,
        task_id: &str,
        expected_version: u64,
        next_state: TaskState,
    ) -> Result<TaskRecord, StateStoreError> {
        self.in_immediate_transaction(|store| {
            let current = store.require_task(task_id)?;
            require_version(&current, task_id, expected_version)?;
            validate_transition(&current, &next_state)?;

            let next_generation = if matches!(next_state, TaskState::Downloading) {
                next_counter(current.generation, "generation")?
            } else {
                current.generation
            };
            let next_version = next_counter(current.version, "version")?;
            let mut statement = store.connection.prepare(
                "UPDATE tasks
                 SET state = ?, failure_message = ?, generation = ?, version = ?,
                     updated_at = CAST(strftime('%s', 'now') AS INTEGER)
                 WHERE id = ? AND version = ?;",
            )?;
            statement.bind((1, state_name(&next_state)))?;
            statement.bind((2, failure_message_value(&next_state)))?;
            statement.bind((3, to_sqlite_integer(next_generation, "generation")?))?;
            statement.bind((4, to_sqlite_integer(next_version, "version")?))?;
            statement.bind((5, task_id))?;
            statement.bind((6, to_sqlite_integer(expected_version, "version")?))?;
            statement.next()?;

            if store.connection.change_count() != 1 {
                return Err(StateStoreError::ConcurrentModification(task_id.to_string()));
            }
            store.require_task(task_id)
        })
    }

    /// Deletes a terminal task record only, without touching its destination file.
    ///
    /// Deletion writes a tombstone in the same transaction so the caller cannot
    /// reuse the ID and create an ABA target for an old worker.
    pub fn delete_task(&self, task_id: &str, expected_version: u64) -> Result<(), StateStoreError> {
        self.in_immediate_transaction(|store| {
            let current = store.require_task(task_id)?;
            require_version(&current, task_id, expected_version)?;
            if matches!(
                current.state,
                TaskState::Pending | TaskState::Downloading | TaskState::Paused
            ) {
                return Err(StateStoreError::ActiveTaskCannotBeDeleted(
                    task_id.to_string(),
                ));
            }

            let mut tombstone = store.connection.prepare(
                "INSERT INTO task_tombstones (id, retired_generation, retired_version, retired_at)
                 VALUES (?, ?, ?, CAST(strftime('%s', 'now') AS INTEGER));",
            )?;
            tombstone.bind((1, task_id))?;
            tombstone.bind((2, to_sqlite_integer(current.generation, "generation")?))?;
            tombstone.bind((3, to_sqlite_integer(current.version, "version")?))?;
            tombstone.next()?;

            let mut delete = store
                .connection
                .prepare("DELETE FROM tasks WHERE id = ? AND version = ?;")?;
            delete.bind((1, task_id))?;
            delete.bind((2, to_sqlite_integer(expected_version, "version")?))?;
            delete.next()?;
            if store.connection.change_count() != 1 {
                return Err(StateStoreError::ConcurrentModification(task_id.to_string()));
            }
            Ok(())
        })
    }

    fn migrate(&self) -> Result<(), StateStoreError> {
        self.in_immediate_transaction(|store| {
            store.connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY CHECK(version > 0),
                    applied_at INTEGER NOT NULL
                );",
            )?;

            let mut version = store.schema_version()?;
            if version > SCHEMA_VERSION {
                return Err(StateStoreError::UnsupportedSchema {
                    found: version,
                    supported: SCHEMA_VERSION,
                });
            }

            while version < SCHEMA_VERSION {
                match version + 1 {
                    1 => store.apply_v1_schema()?,
                    2 => store.apply_v2_schema()?,
                    _ => unreachable!("all supported migrations are listed above"),
                }
                version += 1;
                let mut statement = store.connection.prepare(
                    "INSERT INTO schema_migrations (version, applied_at)
                     VALUES (?, CAST(strftime('%s', 'now') AS INTEGER));",
                )?;
                statement.bind((1, i64::from(version)))?;
                statement.next()?;
            }
            Ok(())
        })
    }

    fn apply_v1_schema(&self) -> Result<(), StateStoreError> {
        self.connection.execute(
            "CREATE TABLE tasks (
                id TEXT PRIMARY KEY NOT NULL CHECK(length(trim(id)) > 0),
                url TEXT NOT NULL CHECK(length(trim(url)) > 0),
                destination TEXT NOT NULL CHECK(length(trim(destination)) > 0),
                file_size INTEGER NOT NULL CHECK(file_size >= 0),
                downloaded_bytes INTEGER NOT NULL
                    CHECK(downloaded_bytes >= 0 AND downloaded_bytes <= file_size),
                etag TEXT,
                last_modified TEXT,
                supports_range INTEGER NOT NULL DEFAULT 0
                    CHECK(supports_range IN (0, 1)),
                state TEXT NOT NULL
                    CHECK(state IN ('pending', 'downloading', 'paused', 'completed', 'failed')),
                failure_message TEXT,
                created_at INTEGER NOT NULL DEFAULT (CAST(strftime('%s', 'now') AS INTEGER)),
                updated_at INTEGER NOT NULL DEFAULT (CAST(strftime('%s', 'now') AS INTEGER)),
                CHECK(
                    (state = 'failed' AND failure_message IS NOT NULL)
                    OR (state <> 'failed' AND failure_message IS NULL)
                )
            );
            CREATE INDEX tasks_by_state ON tasks(state, updated_at DESC);",
        )?;
        Ok(())
    }

    fn apply_v2_schema(&self) -> Result<(), StateStoreError> {
        // V1 did not persist attempt ownership, immutable metadata, or a file
        // finalization hand-off. Quarantining those rows as failed is safer than
        // resuming or reporting any old completion as trustworthy.
        self.connection.execute(
            "ALTER TABLE tasks ADD COLUMN generation INTEGER NOT NULL DEFAULT 0
                CHECK(generation >= 0);
            ALTER TABLE tasks ADD COLUMN version INTEGER NOT NULL DEFAULT 0
                CHECK(version >= 0);
            ALTER TABLE tasks ADD COLUMN metadata_observed INTEGER NOT NULL DEFAULT 0
                CHECK(metadata_observed IN (0, 1));
            ALTER TABLE tasks ADD COLUMN finalization_confirmed INTEGER NOT NULL DEFAULT 0
                CHECK(finalization_confirmed IN (0, 1));
            CREATE TABLE task_tombstones (
                id TEXT PRIMARY KEY NOT NULL CHECK(length(trim(id)) > 0),
                retired_generation INTEGER NOT NULL CHECK(retired_generation >= 0),
                retired_version INTEGER NOT NULL CHECK(retired_version >= 0),
                retired_at INTEGER NOT NULL
            );
            UPDATE tasks
            SET state = 'failed',
                failure_message = 'Task requires revalidation after state-store schema migration.',
                file_size = 0,
                downloaded_bytes = 0,
                etag = NULL,
                last_modified = NULL,
                supports_range = 0,
                generation = 0,
                version = 0,
                metadata_observed = 0,
                finalization_confirmed = 0;",
        )?;
        Ok(())
    }

    fn require_task(&self, task_id: &str) -> Result<TaskRecord, StateStoreError> {
        self.get_task(task_id)?
            .ok_or_else(|| StateStoreError::TaskNotFound(task_id.to_string()))
    }

    fn is_task_id_retired(&self, task_id: &str) -> Result<bool, StateStoreError> {
        let mut statement = self
            .connection
            .prepare("SELECT 1 FROM task_tombstones WHERE id = ?;")?;
        statement.bind((1, task_id))?;
        let mut rows = statement.into_iter();
        Ok(rows.next().transpose()?.is_some())
    }

    fn in_immediate_transaction<T>(
        &self,
        operation: impl FnOnce(&Self) -> Result<T, StateStoreError>,
    ) -> Result<T, StateStoreError> {
        self.connection.execute("BEGIN IMMEDIATE;")?;
        match operation(self) {
            Ok(committed_value) => match self.connection.execute("COMMIT;") {
                Ok(()) => Ok(committed_value),
                Err(error) => {
                    let _ = self.connection.execute("ROLLBACK;");
                    Err(error.into())
                }
            },
            Err(error) => {
                let _ = self.connection.execute("ROLLBACK;");
                Err(error)
            }
        }
    }
}

fn task_from_row(mut row: Row) -> Result<TaskRecord, StateStoreError> {
    let id = String::try_from(row.take(0))?;
    let url = String::try_from(row.take(1))?;
    let destination = String::try_from(row.take(2))?;
    let file_size = from_sqlite_integer(row.try_read(3)?, "file_size")?;
    let downloaded_bytes = from_sqlite_integer(row.try_read(4)?, "downloaded_bytes")?;
    let etag = Option::<String>::try_from(row.take(5))?;
    let last_modified = Option::<String>::try_from(row.take(6))?;
    let supports_range = from_sqlite_bool(row.try_read(7)?, "supports_range")?;
    let state_name = String::try_from(row.take(8))?;
    let failure_message = Option::<String>::try_from(row.take(9))?;
    let generation = from_sqlite_integer(row.try_read(10)?, "generation")?;
    let version = from_sqlite_integer(row.try_read(11)?, "version")?;
    let metadata_observed = from_sqlite_bool(row.try_read(12)?, "metadata_observed")?;
    let finalization_confirmed = from_sqlite_bool(row.try_read(13)?, "finalization_confirmed")?;
    let state = task_state_from_db(&state_name, failure_message)?;

    let task = TaskRecord {
        id,
        url,
        destination,
        file_size,
        downloaded_bytes,
        identity: FileIdentity {
            etag,
            last_modified,
            content_length: file_size,
            supports_range,
        },
        metadata_observed,
        finalization_confirmed,
        generation,
        version,
        state,
    };
    validate_task_record(&task)?;
    Ok(task)
}

fn state_name(state: &TaskState) -> &'static str {
    match state {
        TaskState::Pending => "pending",
        TaskState::Downloading => "downloading",
        TaskState::Paused => "paused",
        TaskState::Completed => "completed",
        TaskState::Failed(_) => "failed",
    }
}

fn failure_message_value(state: &TaskState) -> Value {
    match state {
        TaskState::Failed(message) => Value::from(message.clone()),
        _ => Value::Null,
    }
}

fn task_state_from_db(
    state: &str,
    failure_message: Option<String>,
) -> Result<TaskState, StateStoreError> {
    match (state, failure_message) {
        ("pending", None) => Ok(TaskState::Pending),
        ("downloading", None) => Ok(TaskState::Downloading),
        ("paused", None) => Ok(TaskState::Paused),
        ("completed", None) => Ok(TaskState::Completed),
        ("failed", Some(message)) => Ok(TaskState::Failed(message)),
        (state, message) => Err(StateStoreError::CorruptRecord(format!(
            "state {state:?} has incompatible failure message {message:?}"
        ))),
    }
}

fn validate_new_task(task: &TaskRecord) -> Result<(), StateStoreError> {
    validate_task_record(task)?;
    if task.state != TaskState::Pending
        || task.file_size != 0
        || task.downloaded_bytes != 0
        || task.identity != FileIdentity::default()
        || task.metadata_observed
        || task.finalization_confirmed
        || task.generation != 0
        || task.version != 0
    {
        return Err(StateStoreError::InvalidTaskRecord(
            "new tasks must be fresh Pending records without transfer metadata",
        ));
    }
    Ok(())
}

fn validate_task_record(task: &TaskRecord) -> Result<(), StateStoreError> {
    if task.id.trim().is_empty() {
        return Err(StateStoreError::InvalidTaskRecord(
            "task id must not be empty",
        ));
    }
    if task.url.trim().is_empty() {
        return Err(StateStoreError::InvalidTaskRecord(
            "task URL must not be empty",
        ));
    }
    if task.destination.trim().is_empty() {
        return Err(StateStoreError::InvalidTaskRecord(
            "task destination must not be empty",
        ));
    }
    validate_transfer_observation(task.file_size, task.downloaded_bytes, &task.identity)?;
    to_sqlite_integer(task.generation, "generation")?;
    to_sqlite_integer(task.version, "version")?;

    if !task.metadata_observed
        && (task.file_size != 0
            || task.downloaded_bytes != 0
            || task.identity != FileIdentity::default()
            || task.finalization_confirmed)
    {
        return Err(StateStoreError::InvalidTaskRecord(
            "unobserved metadata must not carry transfer progress or finalization",
        ));
    }
    if task.finalization_confirmed
        && (!task.metadata_observed || task.downloaded_bytes != task.file_size)
    {
        return Err(StateStoreError::InvalidTaskRecord(
            "confirmed finalization requires complete observed metadata",
        ));
    }
    if matches!(task.state, TaskState::Completed)
        && (!task.metadata_observed
            || !task.finalization_confirmed
            || task.downloaded_bytes != task.file_size)
    {
        return Err(StateStoreError::CompletionNotReady(task.id.clone()));
    }
    if let TaskState::Failed(message) = &task.state {
        if message.trim().is_empty() {
            return Err(StateStoreError::InvalidTaskRecord(
                "failure message must not be empty",
            ));
        }
    }
    Ok(())
}

fn validate_transfer_observation(
    file_size: u64,
    downloaded_bytes: u64,
    identity: &FileIdentity,
) -> Result<(), StateStoreError> {
    if downloaded_bytes > file_size {
        return Err(StateStoreError::InvalidTaskRecord(
            "downloaded bytes cannot exceed file size",
        ));
    }
    if identity.content_length != file_size {
        return Err(StateStoreError::InvalidTaskRecord(
            "identity content length must match file size",
        ));
    }
    to_sqlite_integer(file_size, "file_size")?;
    to_sqlite_integer(downloaded_bytes, "downloaded_bytes")?;
    Ok(())
}

fn require_downloading_attempt(
    current: &TaskRecord,
    task_id: &str,
    attempt: DownloadAttempt,
) -> Result<(), StateStoreError> {
    if !matches!(current.state, TaskState::Downloading) {
        return Err(StateStoreError::TaskNotDownloading {
            task_id: task_id.to_string(),
            state: current.state.clone(),
        });
    }
    if current.generation != attempt.generation {
        return Err(StateStoreError::AttemptOwnershipLost {
            task_id: task_id.to_string(),
            expected: attempt.generation,
            actual: current.generation,
        });
    }
    require_version(current, task_id, attempt.version)
}

fn require_version(
    current: &TaskRecord,
    task_id: &str,
    expected_version: u64,
) -> Result<(), StateStoreError> {
    if current.version != expected_version {
        return Err(StateStoreError::VersionConflict {
            task_id: task_id.to_string(),
            expected: expected_version,
            actual: current.version,
        });
    }
    Ok(())
}

fn validate_transition(current: &TaskRecord, next: &TaskState) -> Result<(), StateStoreError> {
    if let TaskState::Failed(message) = next {
        if message.trim().is_empty() {
            return Err(StateStoreError::InvalidTaskRecord(
                "failure message must not be empty",
            ));
        }
    }
    if matches!(
        (&current.state, next),
        (TaskState::Downloading, TaskState::Completed)
    ) && (!current.metadata_observed
        || !current.finalization_confirmed
        || current.downloaded_bytes != current.file_size)
    {
        return Err(StateStoreError::CompletionNotReady(current.id.clone()));
    }
    if current.finalization_confirmed
        && matches!(
            (&current.state, next),
            (
                TaskState::Downloading,
                TaskState::Paused | TaskState::Failed(_)
            )
        )
    {
        return Err(StateStoreError::FinalizationAlreadyConfirmed(
            current.id.clone(),
        ));
    }

    let allowed = matches!(
        (&current.state, next),
        (
            TaskState::Pending,
            TaskState::Downloading | TaskState::Paused | TaskState::Failed(_)
        ) | (
            TaskState::Downloading,
            TaskState::Paused | TaskState::Completed | TaskState::Failed(_)
        ) | (
            TaskState::Paused,
            TaskState::Downloading | TaskState::Failed(_)
        ) | (TaskState::Failed(_), TaskState::Pending)
    );
    if !allowed {
        return Err(StateStoreError::InvalidStateTransition {
            from: current.state.clone(),
            to: next.clone(),
        });
    }
    Ok(())
}

fn next_counter(current_counter: u64, field: &'static str) -> Result<u64, StateStoreError> {
    current_counter
        .checked_add(1)
        .ok_or(StateStoreError::IntegerOutOfRange(field))
        .and_then(|next| {
            to_sqlite_integer(next, field)?;
            Ok(next)
        })
}

fn to_sqlite_integer(unsigned_value: u64, field: &'static str) -> Result<i64, StateStoreError> {
    i64::try_from(unsigned_value).map_err(|_| StateStoreError::IntegerOutOfRange(field))
}

fn from_sqlite_integer(sqlite_value: i64, field: &'static str) -> Result<u64, StateStoreError> {
    u64::try_from(sqlite_value)
        .map_err(|_| StateStoreError::CorruptRecord(format!("negative {field}")))
}

fn from_sqlite_bool(sqlite_value: i64, field: &'static str) -> Result<bool, StateStoreError> {
    match sqlite_value {
        0 => Ok(false),
        1 => Ok(true),
        _ => Err(StateStoreError::CorruptRecord(format!(
            "invalid {field} value: {sqlite_value}"
        ))),
    }
}

fn bool_to_sqlite(flag: bool) -> i64 {
    i64::from(flag)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn new_task() -> TaskRecord {
        TaskRecord::new(
            "task-1",
            "https://example.com/releases/barq.iso",
            "/downloads/barq.iso",
        )
    }

    fn observed_identity(file_size: u64) -> FileIdentity {
        FileIdentity {
            etag: Some("\"release-v1\"".to_string()),
            last_modified: Some("Wed, 21 Oct 2015 07:28:00 GMT".to_string()),
            content_length: file_size,
            supports_range: true,
        }
    }

    fn start_download(store: &StateStore, task: &TaskRecord) -> TaskRecord {
        store.create_task(task).unwrap();
        store
            .transition_task(&task.id, task.version, TaskState::Downloading)
            .unwrap()
    }

    fn transfer_checkpoint(
        task: &TaskRecord,
        file_size: u64,
        downloaded_bytes: u64,
        identity: &FileIdentity,
    ) -> TransferCheckpoint {
        TransferCheckpoint::new(
            task.download_attempt().unwrap(),
            file_size,
            downloaded_bytes,
            identity.clone(),
        )
    }

    #[test]
    fn persistent_store_reopens_with_wal_and_keeps_owned_checkpoint() {
        let temp_dir = tempdir().unwrap();
        let database_path = temp_dir.path().join("barq-engine.sqlite3");
        let task = new_task();
        let identity = observed_identity(1_024);
        let checkpoint;

        {
            let store = StateStore::open(&database_path).unwrap();
            assert_eq!(store.database_path(), database_path.as_path());
            assert_eq!(store.schema_version().unwrap(), SCHEMA_VERSION);
            assert_eq!(store.journal_mode().unwrap().to_lowercase(), "wal");

            let downloading = start_download(&store, &task);
            checkpoint = store
                .update_transfer_state(
                    &task.id,
                    &transfer_checkpoint(&downloading, 1_024, 512, &identity),
                )
                .unwrap();
            assert!(checkpoint.metadata_observed);
            assert_eq!(checkpoint.generation, 1);
        }

        let reopened = StateStore::open(&database_path).unwrap();
        assert_eq!(reopened.journal_mode().unwrap().to_lowercase(), "wal");
        assert_eq!(reopened.get_task(&task.id).unwrap().unwrap(), checkpoint);
    }

    #[test]
    fn stale_worker_and_paused_attempt_cannot_write_progress() {
        let temp_dir = tempdir().unwrap();
        let store = StateStore::open(temp_dir.path().join("barq-engine.sqlite3")).unwrap();
        let task = new_task();
        let identity = observed_identity(1_024);
        let downloading = start_download(&store, &task);
        let checkpoint = store
            .update_transfer_state(
                &task.id,
                &transfer_checkpoint(&downloading, 1_024, 512, &identity),
            )
            .unwrap();
        let paused = store
            .transition_task(&task.id, checkpoint.version, TaskState::Paused)
            .unwrap();

        assert!(matches!(
            store.update_transfer_state(
                &task.id,
                &transfer_checkpoint(&checkpoint, 1_024, 600, &identity),
            ),
            Err(StateStoreError::TaskNotDownloading {
                state: TaskState::Paused,
                ..
            })
        ));

        let resumed = store
            .transition_task(&task.id, paused.version, TaskState::Downloading)
            .unwrap();
        assert_eq!(resumed.generation, checkpoint.generation + 1);
        assert!(matches!(
            store.update_transfer_state(
                &task.id,
                &transfer_checkpoint(&checkpoint, 1_024, 600, &identity),
            ),
            Err(StateStoreError::AttemptOwnershipLost { .. })
        ));
    }

    #[test]
    fn progress_cannot_regress_and_metadata_cannot_change_after_observation() {
        let temp_dir = tempdir().unwrap();
        let store = StateStore::open(temp_dir.path().join("barq-engine.sqlite3")).unwrap();
        let task = new_task();
        let identity = observed_identity(1_024);
        let downloading = start_download(&store, &task);
        let checkpoint = store
            .update_transfer_state(
                &task.id,
                &transfer_checkpoint(&downloading, 1_024, 512, &identity),
            )
            .unwrap();

        assert!(matches!(
            store.update_transfer_state(
                &task.id,
                &transfer_checkpoint(&checkpoint, 1_024, 511, &identity),
            ),
            Err(StateStoreError::ProgressRegression { .. })
        ));
        assert!(matches!(
            store.update_transfer_state(
                &task.id,
                &transfer_checkpoint(&checkpoint, 2_048, 512, &observed_identity(2_048)),
            ),
            Err(StateStoreError::MetadataImmutable(_))
        ));
        assert_eq!(
            store.get_task(&task.id).unwrap().unwrap().downloaded_bytes,
            512
        );
    }

    #[test]
    fn same_attempt_stale_version_is_rejected() {
        let temp_dir = tempdir().unwrap();
        let store = StateStore::open(temp_dir.path().join("barq-engine.sqlite3")).unwrap();
        let task = new_task();
        let identity = observed_identity(1_024);
        let downloading = start_download(&store, &task);
        let first = store
            .update_transfer_state(
                &task.id,
                &transfer_checkpoint(&downloading, 1_024, 256, &identity),
            )
            .unwrap();
        let _second = store
            .update_transfer_state(
                &task.id,
                &transfer_checkpoint(&first, 1_024, 512, &identity),
            )
            .unwrap();

        assert!(matches!(
            store.update_transfer_state(
                &task.id,
                &transfer_checkpoint(&first, 1_024, 768, &identity),
            ),
            Err(StateStoreError::VersionConflict { .. })
        ));
    }

    #[test]
    fn unknown_zero_size_cannot_complete_but_observed_empty_file_can() {
        let temp_dir = tempdir().unwrap();
        let store = StateStore::open(temp_dir.path().join("barq-engine.sqlite3")).unwrap();
        let task = new_task();
        let downloading = start_download(&store, &task);

        assert!(matches!(
            store.transition_task(&task.id, downloading.version, TaskState::Completed),
            Err(StateStoreError::CompletionNotReady(_))
        ));

        let empty_identity = FileIdentity::default();
        let observed_empty = store
            .update_transfer_state(
                &task.id,
                &transfer_checkpoint(&downloading, 0, 0, &empty_identity),
            )
            .unwrap();
        assert!(matches!(
            store.transition_task(&task.id, observed_empty.version, TaskState::Completed,),
            Err(StateStoreError::CompletionNotReady(_))
        ));

        let finalized = store
            .confirm_finalization(&task.id, observed_empty.download_attempt().unwrap())
            .unwrap();
        let completed = store
            .transition_task(&task.id, finalized.version, TaskState::Completed)
            .unwrap();
        assert_eq!(completed.state, TaskState::Completed);
        assert!(completed.metadata_observed);
        assert!(completed.finalization_confirmed);
    }

    #[test]
    fn active_tasks_cannot_be_deleted_and_retired_ids_prevent_aba_reuse() {
        let temp_dir = tempdir().unwrap();
        let store = StateStore::open(temp_dir.path().join("barq-engine.sqlite3")).unwrap();
        let task = new_task();
        store.create_task(&task).unwrap();

        assert!(matches!(
            store.delete_task(&task.id, task.version),
            Err(StateStoreError::ActiveTaskCannotBeDeleted(_))
        ));
        let failed = store
            .transition_task(
                &task.id,
                task.version,
                TaskState::Failed("cancelled by owner".to_string()),
            )
            .unwrap();
        store.delete_task(&task.id, failed.version).unwrap();
        assert!(store.get_task(&task.id).unwrap().is_none());
        assert!(matches!(
            store.create_task(&task),
            Err(StateStoreError::TaskIdRetired(_))
        ));
    }

    #[test]
    fn failed_tasks_can_be_retried_through_pending() {
        let temp_dir = tempdir().unwrap();
        let store = StateStore::open(temp_dir.path().join("barq-engine.sqlite3")).unwrap();
        let task = new_task();
        store.create_task(&task).unwrap();
        let failed = store
            .transition_task(
                &task.id,
                task.version,
                TaskState::Failed("network unavailable".to_string()),
            )
            .unwrap();
        let retried = store
            .transition_task(&task.id, failed.version, TaskState::Pending)
            .unwrap();
        assert_eq!(retried.state, TaskState::Pending);
    }

    #[test]
    fn failed_migration_returns_an_error_without_leaving_partial_schema() {
        let temp_dir = tempdir().unwrap();
        let database_path = temp_dir.path().join("barq-engine.sqlite3");
        let legacy = sqlite::open(&database_path).unwrap();
        legacy
            .execute("CREATE TABLE tasks (legacy_column TEXT);")
            .unwrap();
        drop(legacy);

        let result = StateStore::open(&database_path);
        assert!(matches!(result, Err(StateStoreError::Sqlite(_))));

        let verification = sqlite::open(&database_path).unwrap();
        let statement = verification
            .prepare(
                "SELECT 1 FROM sqlite_master
                 WHERE type = 'table' AND name = 'schema_migrations';",
            )
            .unwrap();
        assert!(statement.into_iter().next().is_none());
    }
}
