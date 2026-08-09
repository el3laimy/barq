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
    /// Returns true only when both observations identify the same byte representation.
    ///
    /// Resume and parallel ranges require a matching strong ETag and a known, identical
    /// content length. A missing or weak validator must restart from byte zero.
    pub fn is_identity_match(&self, other: &FileIdentity) -> bool {
        if self.content_length == 0
            || other.content_length == 0
            || self.content_length != other.content_length
        {
            return false;
        }

        matches!(
            (&self.etag, &other.etag),
            (Some(left), Some(right)) if is_strong_etag(left) && left == right
        )
    }
}

fn is_strong_etag(value: &str) -> bool {
    let normalized = value.trim();
    normalized.len() >= 2 && normalized.starts_with('"') && normalized.ends_with('"')
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

    #[test]
    fn weak_or_missing_validators_cannot_resume() {
        let strong = FileIdentity {
            etag: Some("\"12345\"".to_string()),
            last_modified: Some("Wed, 21 Oct 2015 07:28:00 GMT".to_string()),
            content_length: 1000,
            supports_range: true,
        };
        let weak = FileIdentity {
            etag: Some("W/\"12345\"".to_string()),
            ..strong.clone()
        };
        let missing = FileIdentity {
            etag: None,
            ..strong.clone()
        };

        assert!(!strong.is_identity_match(&weak));
        assert!(!strong.is_identity_match(&missing));
    }
}
