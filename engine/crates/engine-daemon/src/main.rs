//! Barq Standalone Download Engine Daemon (`barq-engine`).

use anyhow::Result;
use ipc_protocol::{decode_client_message, encode_daemon_message, ClientMessage, DaemonMessage};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::TcpListener;
use tracing::{error, info};

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
                let response = match msg {
                    ClientMessage::Hello { client_version } => {
                        info!("Handshake received from client v{}", client_version);
                        DaemonMessage::Capabilities {
                            daemon_version: "0.1.0".to_string(),
                            features: vec![
                                "libcurl-multi".to_string(),
                                "adaptive-scheduler".to_string(),
                                "file-writer-prealloc".to_string(),
                                "sqlite-wal".to_string(),
                            ],
                        }
                    }
                    ClientMessage::CreateTask { url, destination, .. } => {
                        info!("Received task creation request for URL: {}", redact_url(&url));
                        let dest = destination.unwrap_or_else(|| "/tmp/download".to_string());
                        DaemonMessage::TaskSnapshot {
                            task_id: "task-001".to_string(),
                            state: "Pending".to_string(),
                            progress: 0,
                            total: 1024 * 1024,
                            speed: 0.0,
                        }
                    }
                    ClientMessage::ControlTask { task_id, action } => {
                        info!("Control request for task {}: {}", task_id, action);
                        DaemonMessage::TaskEvent {
                            task_id,
                            event_type: "StateChange".to_string(),
                            message: format!("Action {} applied", action),
                        }
                    }
                    ClientMessage::GetDiagnostics => DaemonMessage::Diagnostics {
                        info: "Barq Engine Daemon v0.1.0 Healthy".to_string(),
                    },
                };

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
