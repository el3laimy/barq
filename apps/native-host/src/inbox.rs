use anyhow::Result;
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::Path;
use uuid::Uuid;
use crate::platform::inbox_dir;
use crate::protocol::DownloadEnvelope;

/// Restrict a directory so that only the current user can access it.
pub fn restrict_directory_to_current_user(path: &Path) -> Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(path)?.permissions();
        perms.set_mode(0o700);
        fs::set_permissions(path, perms)?;
    }
    Ok(())
}

/// Sync the parent directory to ensure the rename is durable on Unix.
pub fn sync_parent_directory(path: &Path) -> Result<()> {
    #[cfg(unix)]
    {
        if let Some(parent) = path.parent() {
            let f = File::open(parent)?;
            f.sync_all()?;
        }
    }
    Ok(())
}

/// Persist a DownloadEnvelope to the durable inbox.
///
/// The write follows the pattern: tmp file → fsync → atomic rename → parent sync.
/// This ensures that the file is fully written before it becomes visible in the inbox.
pub fn persist_envelope(inbox: &Path, envelope: &DownloadEnvelope) -> Result<Uuid> {
    fs::create_dir_all(inbox)?;
    restrict_directory_to_current_user(inbox)?;

    let transfer_id = Uuid::new_v4();
    let tmp = inbox.join(format!(".{transfer_id}.tmp"));
    let final_path = inbox.join(format!("{transfer_id}.json"));

    let bytes = serde_json::to_vec(envelope)?;

    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&tmp)?;
    file.write_all(&bytes)?;
    file.sync_all()?;

    fs::rename(&tmp, &final_path)?; // atomic within same filesystem
    sync_parent_directory(inbox)?;

    tracing::info!(
        transfer_id = %transfer_id,
        url_len = envelope.request.url.len(),
        "Envelope persisted to durable inbox"
    );

    Ok(transfer_id)
}

/// Persist an envelope with idempotency checking.
///
/// If an envelope with the same idempotency key already exists in the inbox,
/// return the existing transfer ID instead of creating a duplicate.
pub fn persist_idempotent(envelope: &DownloadEnvelope) -> Result<Uuid> {
    let inbox = inbox_dir();

    // Check for existing envelope with same idempotency key
    if let Ok(entries) = fs::read_dir(&inbox) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().map_or(false, |e| e == "json") {
                if let Ok(content) = fs::read_to_string(&path) {
                    if let Ok(existing) = serde_json::from_str::<DownloadEnvelope>(&content) {
                        if existing.idempotency_key == envelope.idempotency_key {
                            // Extract transfer_id from filename
                            if let Some(stem) = path.file_stem().and_then(|s| s.to_str()) {
                                if let Ok(id) = Uuid::parse_str(stem) {
                                    tracing::info!(
                                        transfer_id = %id,
                                        "Duplicate envelope detected by idempotency key, returning existing"
                                    );
                                    return Ok(id);
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    persist_envelope(&inbox, envelope)
}
