//! Barq Standalone Download Engine Daemon (`barq-engine`).

use anyhow::Result;
use ipc_protocol::{
    decode_client_message, encode_daemon_message, ClientMessage, DaemonErrorCode, DaemonMessage,
};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::TcpListener;
use tracing::{error, info};
use transport_curl::linked_version;

fn redact_url(url: &str) -> String {
    let mut parts = url.splitn(2, '?');
    let base = parts.next().unwrap_or("");
    let query = match parts.next() {
        Some(q) => q,
        None => return url.to_string(),
    };

    let keywords = ["token", "key", "auth", "password", "secret", "session"];

    let redacted_query = query
        .split('&')
        .map(|param| {
            let mut param_parts = param.splitn(2, '=');
            let key = param_parts.next().unwrap_or("");
            let val = param_parts.next();

            let key_lower = key.to_lowercase();
            let is_sensitive = keywords.iter().any(|k| key_lower.contains(k));

            if is_sensitive && val.is_some() {
                format!("{}={}", key, "[REDACTED]")
            } else {
                param.to_string()
            }
        })
        .collect::<Vec<_>>()
        .join("&");

    format!("{}?{}", base, redacted_query)
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt::init();

    info!("⚡ Starting Barq Download Engine Daemon v0.1.0...");

    let bind_addr = "127.0.0.1:19376";
    let listener = TcpListener::bind(bind_addr).await?;
    info!("IPC Daemon listening on {}", bind_addr);

    loop {
        match listener.accept().await {
            Ok((stream, peer)) => {
                info!("New IPC connection from {}", peer);
                tokio::spawn(async move {
                    if let Err(e) = handle_connection(stream).await {
                        error!("IPC connection error: {}", e);
                    }
                });
            }
            Err(e) => {
                error!("Listener accept error: {}", e);
            }
        }
    }
}

async fn handle_connection(stream: tokio::net::TcpStream) -> Result<()> {
    let (reader, mut writer) = stream.into_split();
    let mut lines = BufReader::new(reader).lines();

    while let Some(line) = lines.next_line().await? {
        if line.trim().is_empty() {
            continue;
        }

        match decode_client_message(&line) {
            Ok(msg) => {
                let response = daemon_response(msg);

                let encoded = encode_daemon_message(&response)?;
                writer.write_all(encoded.as_bytes()).await?;
                writer.flush().await?;
            }
            Err(e) => {
                error!("Failed to decode IPC message: {}", e);
            }
        }
    }

    Ok(())
}

fn daemon_response(message: ClientMessage) -> DaemonMessage {
    match message {
        ClientMessage::Hello { client_version } => {
            info!("Handshake received from client v{}", client_version);
            DaemonMessage::Capabilities {
                daemon_version: "0.1.0".to_string(),
                features: Vec::new(),
            }
        }
        ClientMessage::CreateTask { url, .. } => {
            info!(
                "Rejected task creation request for URL: {}",
                redact_url(&url)
            );
            engine_not_ready_error()
        }
        ClientMessage::ControlTask { task_id, action } => {
            info!("Rejected control request for task {}: {}", task_id, action);
            engine_not_ready_error()
        }
        ClientMessage::GetDiagnostics => DaemonMessage::Diagnostics {
            info: format!(
                "Barq Engine Daemon v0.1.0: download execution is not implemented; linked libcurl {} is idle.",
                linked_version()
            ),
        },
    }
}

fn engine_not_ready_error() -> DaemonMessage {
    DaemonMessage::Error {
        code: DaemonErrorCode::EngineNotReady,
        message: "Download execution is not implemented in this daemon release.".to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn create_task_is_rejected_until_download_lifecycle_exists() {
        let response = daemon_response(ClientMessage::CreateTask {
            url: "https://example.com/archive.zip".to_string(),
            destination: Some("/tmp/archive.zip".to_string()),
            cookies: None,
            referrer: None,
            user_agent: None,
        });

        assert!(matches!(
            response,
            DaemonMessage::Error {
                code: DaemonErrorCode::EngineNotReady,
                ..
            }
        ));
    }

    #[test]
    fn control_task_is_rejected_until_download_lifecycle_exists() {
        let response = daemon_response(ClientMessage::ControlTask {
            task_id: "unimplemented-task".to_string(),
            action: "Pause".to_string(),
        });

        assert!(matches!(
            response,
            DaemonMessage::Error {
                code: DaemonErrorCode::EngineNotReady,
                ..
            }
        ));
    }
}
