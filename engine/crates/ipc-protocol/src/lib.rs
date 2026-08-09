//! Typed IPC message structures and line-delimited JSON framing for Client <-> Daemon protocol.

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Error, Debug)]
pub enum ProtocolError {
    #[error("Serialization error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "type", content = "payload")]
pub enum ClientMessage {
    Hello {
        client_version: String,
    },
    CreateTask {
        url: String,
        destination: Option<String>,
        cookies: Option<String>,
        referrer: Option<String>,
        user_agent: Option<String>,
    },
    ControlTask {
        task_id: String,
        action: String,
    },
    GetDiagnostics,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "type", content = "payload")]
pub enum DaemonMessage {
    Capabilities {
        daemon_version: String,
        features: Vec<String>,
    },
    TaskSnapshot {
        task_id: String,
        state: String,
        progress: u64,
        total: u64,
        speed: f64,
    },
    TaskEvent {
        task_id: String,
        event_type: String,
        message: String,
    },
    Diagnostics {
        info: String,
    },
    Error {
        code: DaemonErrorCode,
        message: String,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum DaemonErrorCode {
    EngineNotReady,
}

pub fn encode_client_message(msg: &ClientMessage) -> Result<String, ProtocolError> {
    let mut json = serde_json::to_string(msg)?;
    json.push('\n');
    Ok(json)
}

pub fn decode_client_message(line: &str) -> Result<ClientMessage, ProtocolError> {
    let msg = serde_json::from_str(line.trim())?;
    Ok(msg)
}

pub fn encode_daemon_message(msg: &DaemonMessage) -> Result<String, ProtocolError> {
    let mut json = serde_json::to_string(msg)?;
    json.push('\n');
    Ok(json)
}

pub fn decode_daemon_message(line: &str) -> Result<DaemonMessage, ProtocolError> {
    let msg = serde_json::from_str(line.trim())?;
    Ok(msg)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ipc_serialization() {
        let msg = ClientMessage::Hello {
            client_version: "1.0.0".to_string(),
        };
        let encoded = encode_client_message(&msg).unwrap();
        assert!(encoded.ends_with('\n'));
        let decoded = decode_client_message(&encoded).unwrap();
        assert_eq!(msg, decoded);
    }

    #[test]
    fn engine_not_ready_error_round_trips_with_stable_code() {
        let message = DaemonMessage::Error {
            code: DaemonErrorCode::EngineNotReady,
            message: "Download execution is not implemented.".to_string(),
        };

        let encoded = encode_daemon_message(&message).unwrap();
        assert!(encoded.contains("ENGINE_NOT_READY"));
        assert_eq!(decode_daemon_message(&encoded).unwrap(), message);
    }
}
