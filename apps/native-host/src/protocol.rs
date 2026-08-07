use serde::{Deserialize, Serialize};
use uuid::Uuid;
use crate::inbox::persist_idempotent;
use crate::platform::ensure_barq_running;

// ─── Download Envelope ───────────────────────────────────────────────

#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(rename_all = "camelCase")]
pub struct DownloadEnvelope {
    pub protocol: String,
    pub request_id: Uuid,
    pub idempotency_key: String,
    pub created_at: String,
    pub source: String,
    pub request: RequestInfo,
    pub file: FileInfo,
    pub browser: BrowserInfo,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub media: Option<MediaInfo>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(rename_all = "camelCase")]
pub struct RequestInfo {
    pub url: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub final_url: Option<String>,
    #[serde(default = "default_method")]
    pub method: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub referrer: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub page_url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub initiator: Option<String>,
    #[serde(default)]
    pub headers: std::collections::HashMap<String, String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cookie_header: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub body: Option<String>,
}

fn default_method() -> String {
    "GET".to_string()
}

#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(rename_all = "camelCase")]
pub struct FileInfo {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub suggested_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mime_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub size: Option<u64>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(rename_all = "camelCase")]
pub struct BrowserInfo {
    pub family: String,
    pub version: String,
    pub profile_mode: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cookie_store_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tab_id: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub frame_id: Option<i32>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(rename_all = "camelCase")]
pub struct MediaInfo {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub page_title: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub candidates: Option<Vec<MediaCandidate>>,
    #[serde(default)]
    pub drm_detected: bool,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(rename_all = "camelCase")]
pub struct MediaCandidate {
    pub url: String,
    pub kind: String,
}

// ─── Host Request (Extension → Host) ─────────────────────────────────

#[derive(Serialize, Deserialize, Debug)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum HostRequest {
    Hello {
        protocols: Vec<String>,
        #[serde(rename = "extensionVersion")]
        extension_version: String,
        browser: HelloBrowser,
        capabilities: Vec<String>,
    },
    PrepareCapture {
        #[serde(rename = "correlationId")]
        correlation_id: String,
        envelope: DownloadEnvelope,
    },
}

#[derive(Serialize, Deserialize, Debug)]
pub struct HelloBrowser {
    pub family: String,
    pub version: String,
}

// ─── Host Response (Host → Extension) ────────────────────────────────

#[derive(Serialize, Debug)]
#[serde(untagged)]
pub enum HostResponse {
    HelloAck {
        #[serde(rename = "type")]
        msg_type: &'static str,
        protocol: &'static str,
        #[serde(rename = "hostVersion")]
        host_version: String,
        healthy: bool,
        capabilities: Vec<String>,
        limits: HostLimits,
    },
    Accepted {
        status: &'static str,
        #[serde(rename = "correlationId")]
        correlation_id: String,
        #[serde(rename = "transferId")]
        transfer_id: String,
        durable: bool,
    },
    Rejected {
        status: &'static str,
        #[serde(rename = "correlationId")]
        correlation_id: String,
        code: String,
        retryable: bool,
    },
}

#[derive(Serialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct HostLimits {
    pub max_message_bytes: usize,
    pub max_cookie_bytes: usize,
}

impl HostResponse {
    pub fn hello_ack() -> Self {
        Self::HelloAck {
            msg_type: "hello_ack",
            protocol: "barq.browser.v1",
            host_version: env!("CARGO_PKG_VERSION").to_string(),
            healthy: true,
            capabilities: vec![
                "durable-inbox".to_string(),
                "media-page-handoff".to_string(),
            ],
            limits: HostLimits {
                max_message_bytes: 900_000,
                max_cookie_bytes: 64_000,
            },
        }
    }

    pub fn accepted(correlation_id: String, transfer_id: Uuid) -> Self {
        Self::Accepted {
            status: "accepted",
            correlation_id,
            transfer_id: transfer_id.to_string(),
            durable: true,
        }
    }

    pub fn rejected(correlation_id: String, code: &str, retryable: bool) -> Self {
        Self::Rejected {
            status: "rejected",
            correlation_id,
            code: code.to_string(),
            retryable,
        }
    }

    pub fn invalid_request(_error: String) -> Self {
        Self::Rejected {
            status: "rejected",
            correlation_id: String::new(),
            code: "INVALID_REQUEST".to_string(),
            retryable: false,
        }
    }
}

// ─── Host Service ────────────────────────────────────────────────────

pub struct HostService {
    _config: (),
}

impl HostService {
    pub fn new(config: ()) -> anyhow::Result<Self> {
        Ok(Self { _config: config })
    }

    pub fn handle(&self, request: HostRequest) -> HostResponse {
        match request {
            HostRequest::Hello { protocols, .. } => {
                if !protocols.contains(&"barq.browser.v1".to_string()) {
                    return HostResponse::rejected(
                        String::new(),
                        "APP_PROTOCOL_TOO_OLD",
                        false,
                    );
                }
                HostResponse::hello_ack()
            }
            HostRequest::PrepareCapture {
                correlation_id,
                envelope,
            } => self.prepare_capture(correlation_id, envelope),
        }
    }

    fn prepare_capture(
        &self,
        correlation_id: String,
        envelope: DownloadEnvelope,
    ) -> HostResponse {
        // Check DRM
        if envelope
            .media
            .as_ref()
            .is_some_and(|m| m.drm_detected)
        {
            return HostResponse::rejected(correlation_id, "DRM_PROTECTED", false);
        }

        // Persist to durable inbox
        match persist_idempotent(&envelope) {
            Ok(transfer_id) => {
                // Best-effort: try to wake up the desktop app
                let _ = ensure_barq_running();
                HostResponse::accepted(correlation_id, transfer_id)
            }
            Err(_e) => HostResponse::rejected(
                correlation_id,
                "QUEUE_UNAVAILABLE",
                true, // retryable
            ),
        }
    }
}
