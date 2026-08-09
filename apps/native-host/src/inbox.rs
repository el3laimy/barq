use anyhow::{bail, Context, Result};
use sha2::{Digest, Sha256};
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;
use uuid::Uuid;

use crate::protocol::DownloadEnvelope;

const IDEMPOTENCY_DIRECTORY: &str = ".idempotency";
const LOCK_ATTEMPTS: usize = 20;
const LOCK_WAIT: Duration = Duration::from_millis(25);

#[cfg(windows)]
const MOVEFILE_REPLACE_EXISTING: u32 = 0x0000_0001;
#[cfg(windows)]
const MOVEFILE_WRITE_THROUGH: u32 = 0x0000_0008;

#[cfg(windows)]
#[link(name = "Kernel32")]
extern "system" {
    #[link_name = "MoveFileExW"]
    fn move_file_ex_w(existing_file_name: *const u16, new_file_name: *const u16, flags: u32)
        -> i32;
}

pub fn restrict_directory_to_current_user(path: &Path) -> Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        let mut permissions = fs::metadata(path)?.permissions();
        permissions.set_mode(0o700);
        fs::set_permissions(path, permissions)?;
    }

    Ok(())
}

pub fn sync_parent_directory(path: &Path) -> Result<()> {
    #[cfg(unix)]
    {
        if let Some(parent) = path.parent() {
            File::open(parent)?.sync_all()?;
        }
    }

    Ok(())
}

pub fn persist_idempotent(inbox: &Path, envelope: &DownloadEnvelope) -> Result<Uuid> {
    prepare_inbox(inbox)?;
    let _idempotency_lock = acquire_idempotency_lock(inbox, &envelope.idempotency_key)?;

    if let Some(transfer_id) = known_transfer_id(inbox, &envelope.idempotency_key)? {
        ensure_envelope_is_published(inbox, transfer_id)?;
        return Ok(transfer_id);
    }

    let transfer_id = Uuid::new_v4();
    let staged_path = stage_envelope(inbox, transfer_id, envelope)?;
    persist_idempotency_record(inbox, &envelope.idempotency_key, transfer_id)?;
    publish_staged_envelope(inbox, transfer_id, &staged_path)?;

    tracing::info!(transfer_id = %transfer_id, "Envelope persisted to durable inbox");
    Ok(transfer_id)
}

fn prepare_inbox(inbox: &Path) -> Result<()> {
    fs::create_dir_all(inbox)?;
    restrict_directory_to_current_user(inbox)?;

    let idempotency_dir = idempotency_dir(inbox);
    fs::create_dir_all(&idempotency_dir)?;
    restrict_directory_to_current_user(&idempotency_dir)
}

fn stage_envelope(inbox: &Path, transfer_id: Uuid, envelope: &DownloadEnvelope) -> Result<PathBuf> {
    let staged_path = staged_envelope_path(inbox, transfer_id);
    let envelope_bytes =
        serde_json::to_vec(envelope).context("Could not serialize download envelope")?;
    write_durable_file(&staged_path, &envelope_bytes)?;
    sync_parent_directory(&staged_path)?;
    Ok(staged_path)
}

fn write_durable_file(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut envelope_file = open_private_new(path)?;
    envelope_file.write_all(bytes)?;
    envelope_file.sync_all()?;
    Ok(())
}

fn durable_rename(source: &Path, destination: &Path) -> Result<()> {
    #[cfg(unix)]
    {
        fs::rename(source, destination).context("Could not publish durable inbox file")?;
        sync_parent_directory(destination)?;
    }

    #[cfg(windows)]
    {
        use std::iter::once;
        use std::os::windows::ffi::OsStrExt;

        let source_wide = source
            .as_os_str()
            .encode_wide()
            .chain(once(0))
            .collect::<Vec<_>>();
        let destination_wide = destination
            .as_os_str()
            .encode_wide()
            .chain(once(0))
            .collect::<Vec<_>>();
        // Both paths are in the same inbox directory.  WRITE_THROUGH makes
        // the final publish visible on disk before a durable ACK is emitted.
        if unsafe {
            move_file_ex_w(
                source_wide.as_ptr(),
                destination_wide.as_ptr(),
                MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
            )
        } == 0
        {
            bail!(
                "Could not durably publish inbox file: {}",
                std::io::Error::last_os_error()
            );
        }
    }

    Ok(())
}

fn open_private_new(path: &Path) -> std::io::Result<File> {
    let mut options = OpenOptions::new();
    options.create_new(true).write(true);

    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;

        options.mode(0o600);
    }

    options.open(path)
}

fn known_transfer_id(inbox: &Path, idempotency_key: &str) -> Result<Option<Uuid>> {
    if let Some(transfer_id) = read_idempotency_record(inbox, idempotency_key)? {
        return Ok(Some(transfer_id));
    }

    let Some(transfer_id) = find_envelope_transfer_id(inbox, idempotency_key)? else {
        return Ok(None);
    };
    persist_idempotency_record(inbox, idempotency_key, transfer_id)?;
    Ok(Some(transfer_id))
}

fn find_envelope_transfer_id(inbox: &Path, idempotency_key: &str) -> Result<Option<Uuid>> {
    for directory_entry in fs::read_dir(inbox)? {
        let envelope_path = directory_entry?.path();
        if !is_envelope_path(&envelope_path) {
            continue;
        }

        let envelope_bytes = fs::read(&envelope_path)?;
        let Ok(existing_envelope) = serde_json::from_slice::<DownloadEnvelope>(&envelope_bytes)
        else {
            continue;
        };

        if existing_envelope.idempotency_key == idempotency_key {
            if let Some(transfer_id) = transfer_id_from_path(&envelope_path) {
                return Ok(Some(transfer_id));
            }
        }
    }

    Ok(None)
}

fn is_envelope_path(path: &Path) -> bool {
    matches!(
        path.extension().and_then(|extension| extension.to_str()),
        Some("json") | Some("pending")
    )
}

fn transfer_id_from_path(path: &Path) -> Option<Uuid> {
    let filename = path.file_stem()?.to_str()?;
    Uuid::parse_str(filename).ok()
}

fn persist_idempotency_record(
    inbox: &Path,
    idempotency_key: &str,
    transfer_id: Uuid,
) -> Result<()> {
    if let Some(existing_transfer_id) = read_idempotency_record(inbox, idempotency_key)? {
        if existing_transfer_id != transfer_id {
            bail!("Idempotency key is already associated with another transfer");
        }
        return Ok(());
    }

    let record_path = idempotency_record_path(inbox, idempotency_key);
    let temporary_path = record_path.with_extension(format!("{}.tmp", Uuid::new_v4()));
    write_durable_file(&temporary_path, transfer_id.to_string().as_bytes())?;
    durable_rename(&temporary_path, &record_path)
}

fn read_idempotency_record(inbox: &Path, idempotency_key: &str) -> Result<Option<Uuid>> {
    let record_path = idempotency_record_path(inbox, idempotency_key);
    let record = match fs::read_to_string(record_path) {
        Ok(record) => record,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };

    let transfer_id = Uuid::parse_str(record.trim()).context("Idempotency record is invalid")?;
    Ok(Some(transfer_id))
}

fn ensure_envelope_is_published(inbox: &Path, transfer_id: Uuid) -> Result<()> {
    let published_path = published_envelope_path(inbox, transfer_id);
    if published_path.exists() {
        return Ok(());
    }

    let staged_path = staged_envelope_path(inbox, transfer_id);
    if staged_path.exists() {
        publish_staged_envelope(inbox, transfer_id, &staged_path)?;
    }

    Ok(())
}

fn publish_staged_envelope(inbox: &Path, transfer_id: Uuid, staged_path: &Path) -> Result<()> {
    let published_path = published_envelope_path(inbox, transfer_id);
    durable_rename(staged_path, &published_path)
}

fn idempotency_dir(inbox: &Path) -> PathBuf {
    inbox.join(IDEMPOTENCY_DIRECTORY)
}

fn idempotency_record_path(inbox: &Path, idempotency_key: &str) -> PathBuf {
    idempotency_dir(inbox).join(format!("{}.record", idempotency_digest(idempotency_key)))
}

fn staged_envelope_path(inbox: &Path, transfer_id: Uuid) -> PathBuf {
    inbox.join(format!("{transfer_id}.pending"))
}

fn published_envelope_path(inbox: &Path, transfer_id: Uuid) -> PathBuf {
    inbox.join(format!("{transfer_id}.json"))
}

fn acquire_idempotency_lock(inbox: &Path, idempotency_key: &str) -> Result<IdempotencyLock> {
    let lock_path =
        idempotency_dir(inbox).join(format!("{}.lock", idempotency_digest(idempotency_key)));

    for attempt in 0..LOCK_ATTEMPTS {
        match open_private_new(&lock_path) {
            Ok(_) => return Ok(IdempotencyLock { path: lock_path }),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                if attempt + 1 < LOCK_ATTEMPTS {
                    thread::sleep(LOCK_WAIT);
                }
            }
            Err(error) => return Err(error.into()),
        }
    }

    bail!("A duplicate download request is still being persisted")
}

fn idempotency_digest(idempotency_key: &str) -> String {
    format!("{:x}", Sha256::digest(idempotency_key.as_bytes()))
}

struct IdempotencyLock {
    path: PathBuf,
}

impl Drop for IdempotencyLock {
    fn drop(&mut self) {
        // A stale lock causes a retryable host rejection instead of duplicate persistence.
        let _ = fs::remove_file(&self.path);
    }
}

#[cfg(test)]
mod tests {
    use super::persist_idempotent;
    use crate::protocol::{BrowserInfo, DownloadEnvelope, FileInfo, RequestInfo};
    use std::fs;
    use std::path::{Path, PathBuf};
    use uuid::Uuid;

    struct TemporaryInbox {
        path: PathBuf,
    }

    impl TemporaryInbox {
        fn new() -> Self {
            let path =
                std::env::temp_dir().join(format!("barq-native-host-test-{}", Uuid::new_v4()));
            fs::create_dir(&path).expect("temporary inbox should be created");
            Self { path }
        }

        fn path(&self) -> &Path {
            &self.path
        }
    }

    impl Drop for TemporaryInbox {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.path);
        }
    }

    fn envelope(idempotency_key: &str) -> DownloadEnvelope {
        DownloadEnvelope {
            protocol: "barq.browser.v1".to_string(),
            request_id: Uuid::new_v4(),
            idempotency_key: idempotency_key.to_string(),
            created_at: "2026-08-08T12:00:00Z".to_string(),
            source: "context-menu".to_string(),
            request: RequestInfo {
                url: "https://example.com/archive.zip".to_string(),
                final_url: None,
                method: "GET".to_string(),
                referrer: None,
                page_url: None,
                initiator: None,
                headers: Default::default(),
                cookie_header: None,
                body: None,
            },
            file: FileInfo {
                suggested_name: Some("archive.zip".to_string()),
                mime_type: Some("application/zip".to_string()),
                size: Some(1024),
            },
            browser: BrowserInfo {
                family: "chrome".to_string(),
                version: "128.0".to_string(),
                profile_mode: "normal".to_string(),
                cookie_store_id: None,
                tab_id: Some(7),
                frame_id: Some(0),
            },
            media: None,
        }
    }

    #[test]
    fn repeated_request_reuses_the_original_transfer_id_after_delivery() {
        let inbox = TemporaryInbox::new();
        let request = envelope(&"a".repeat(32));

        let first_transfer =
            persist_idempotent(inbox.path(), &request).expect("first request should persist");
        let delivered_path = inbox.path().join(format!("{first_transfer}.json"));
        fs::remove_file(delivered_path).expect("simulated watcher should consume the envelope");
        let second_transfer = persist_idempotent(inbox.path(), &request)
            .expect("duplicate request should be accepted");

        assert_eq!(first_transfer, second_transfer);
        assert!(!inbox.path().join(format!("{first_transfer}.json")).exists());
    }

    #[test]
    fn concurrent_duplicates_publish_one_envelope() {
        let inbox = TemporaryInbox::new();
        let request = envelope(&"b".repeat(32));
        let first_inbox = inbox.path().to_path_buf();
        let second_inbox = inbox.path().to_path_buf();
        let first_request = request.clone();
        let second_request = request.clone();

        let first_writer =
            std::thread::spawn(move || persist_idempotent(&first_inbox, &first_request));
        let second_writer =
            std::thread::spawn(move || persist_idempotent(&second_inbox, &second_request));
        let first_transfer = first_writer
            .join()
            .expect("first writer should not panic")
            .expect("first writer should persist");
        let second_transfer = second_writer
            .join()
            .expect("second writer should not panic")
            .expect("second writer should reuse the request");

        let envelopes = fs::read_dir(inbox.path())
            .expect("inbox should remain readable")
            .filter_map(Result::ok)
            .filter(|entry| {
                entry
                    .path()
                    .extension()
                    .is_some_and(|extension| extension == "json")
            })
            .count();

        assert_eq!(first_transfer, second_transfer);
        assert_eq!(envelopes, 1);
    }
}
