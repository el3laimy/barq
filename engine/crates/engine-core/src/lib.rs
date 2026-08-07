//! Core task structures, File Identity, and lifecycle definitions for Barq Download Engine.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum TaskState {
    Pending,
    Downloading,
    Paused,
    Completed,
    Failed(String),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Default)]
pub struct FileIdentity {
    pub etag: Option<String>,
    pub last_modified: Option<String>,
    pub content_length: u64,
    pub supports_range: bool,
}

impl FileIdentity {
    /// Compares this identity with another to determine if they match.
    ///
    /// If there is no identifying information at all (both `etag` and `last_modified`
    /// are `None`) and content_lengths don't differ, this function deliberately falls back
    /// to returning `true`. This is a risk for false positives but is an acceptable fallback
    /// when servers don't provide validation headers.
    pub fn is_identity_match(&self, other: &FileIdentity) -> bool {
        if self.content_length > 0 && other.content_length > 0 && self.content_length != other.content_length {
            return false;
        }
        if let (Some(e1), Some(e2)) = (&self.etag, &other.etag) {
            return e1 == e2;
        }
        if let (Some(m1), Some(m2)) = (&self.last_modified, &other.last_modified) {
            return m1 == m2;
        }
        true
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DownloadTask {
    pub id: String,
    pub url: String,
    pub destination: String,
    pub file_size: u64,
    pub downloaded_bytes: u64,
    pub identity: FileIdentity,
    pub state: TaskState,
}

impl DownloadTask {
    pub fn new(id: String, url: String, destination: String) -> Self {
        Self {
            id,
            url,
            destination,
            file_size: 0,
            downloaded_bytes: 0,
            identity: FileIdentity::default(),
            state: TaskState::Pending,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_task_creation() {
        let task = DownloadTask::new(
            "task-1".to_string(),
            "https://example.com/file.zip".to_string(),
            "/tmp/file.zip".to_string(),
        );
        assert_eq!(task.state, TaskState::Pending);
        assert_eq!(task.downloaded_bytes, 0);
    }

    #[test]
    fn test_identity_matching() {
        let id1 = FileIdentity {
            etag: Some("\"12345\"".to_string()),
            last_modified: None,
            content_length: 1000,
            supports_range: true,
        };
        let id2 = FileIdentity {
            etag: Some("\"12345\"".to_string()),
            last_modified: None,
            content_length: 1000,
            supports_range: true,
        };
        assert!(id1.is_identity_match(&id2));
    }
}
