use anyhow::{bail, Result};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use url::Url;
use uuid::Uuid;

use crate::inbox::persist_idempotent;

pub const PROTOCOL_NAME: &str = "barq.browser.v1";
pub const MAX_COOKIE_BYTES: usize = 64_000;

const MAX_URL_BYTES: usize = 16 * 1024;
const MAX_BODY_BYTES: usize = 64_000;
const MAX_HEADER_BYTES: usize = 64_000;
const MAX_HEADER_COUNT: usize = 100;
const MAX_CAPABILITIES: usize = 32;
const MAX_PROTOCOLS: usize = 8;
const SUPPORTED_HTTP_METHODS: &[&str] = &["GET", "HEAD", "POST"];
const BROWSER_FAMILIES: &[&str] = &[
    "chrome", "edge", "firefox", "chromium", "brave", "opera", "vivaldi",
];
const PROFILE_MODES: &[&str] = &["normal", "incognito", "container"];
const REQUEST_SOURCES: &[&str] = &[
    "auto-download",
    "context-menu",
    "toolbar",
    "media",
    "blob-relay",
];
const MEDIA_KINDS: &[&str] = &["hls", "dash", "media-file", "page"];

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

impl DownloadEnvelope {
    pub fn validate(&self) -> Result<()> {
        validate_exact_value(&self.protocol, PROTOCOL_NAME, "protocol")?;
        validate_idempotency_key(&self.idempotency_key)?;
        validate_timestamp(&self.created_at)?;
        validate_source(&self.source)?;
        self.request.validate()?;
        self.file.validate()?;
        self.browser.validate()?;

        if let Some(media) = &self.media {
            media.validate()?;
        }

        Ok(())
    }
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
    pub headers: HashMap<String, String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cookie_header: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub body: Option<String>,
}

impl RequestInfo {
    fn validate(&self) -> Result<()> {
        validate_http_url(&self.url, "request URL")?;
        validate_optional_http_url(&self.final_url, "final URL")?;
        validate_optional_http_url(&self.referrer, "referrer")?;
        validate_optional_http_url(&self.page_url, "page URL")?;
        validate_exact_member(&self.method, SUPPORTED_HTTP_METHODS, "request method")?;
        validate_optional_text(&self.initiator, 512, "initiator")?;
        validate_headers(&self.headers)?;
        validate_optional_cookie_header(&self.cookie_header)?;
        validate_optional_bytes(&self.body, MAX_BODY_BYTES, "request body")
    }
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

impl FileInfo {
    fn validate(&self) -> Result<()> {
        validate_optional_text(&self.suggested_name, 255, "suggested filename")?;
        validate_optional_text(&self.mime_type, 255, "MIME type")
    }
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

impl BrowserInfo {
    fn validate(&self) -> Result<()> {
        validate_exact_member(&self.family, BROWSER_FAMILIES, "browser family")?;
        validate_text(&self.version, 128, "browser version")?;
        validate_exact_member(&self.profile_mode, PROFILE_MODES, "browser profile mode")?;
        validate_optional_text(&self.cookie_store_id, 256, "cookie store ID")
    }
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

impl MediaInfo {
    fn validate(&self) -> Result<()> {
        validate_optional_text(&self.page_title, 512, "media page title")?;
        let Some(candidates) = &self.candidates else {
            return Ok(());
        };

        if candidates.len() > 50 {
            bail!("Too many media candidates");
        }

        for candidate in candidates {
            candidate.validate()?;
        }

        Ok(())
    }
}

#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(rename_all = "camelCase")]
pub struct MediaCandidate {
    pub url: String,
    pub kind: String,
}

impl MediaCandidate {
    fn validate(&self) -> Result<()> {
        validate_http_url(&self.url, "media candidate URL")?;
        validate_exact_member(&self.kind, MEDIA_KINDS, "media kind")
    }
}

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
        envelope: Box<DownloadEnvelope>,
    },
}

#[derive(Serialize, Deserialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct HelloBrowser {
    pub family: String,
    pub version: String,
}

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
            protocol: PROTOCOL_NAME,
            host_version: env!("CARGO_PKG_VERSION").to_string(),
            healthy: true,
            capabilities: vec![
                "durable-inbox".to_string(),
                "media-page-handoff".to_string(),
            ],
            limits: HostLimits {
                max_message_bytes: 900_000,
                max_cookie_bytes: MAX_COOKIE_BYTES,
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

    pub fn invalid_request() -> Self {
        Self::Rejected {
            status: "rejected",
            correlation_id: String::new(),
            code: "INVALID_REQUEST".to_string(),
            retryable: false,
        }
    }

    pub fn is_accepted(&self) -> bool {
        matches!(self, Self::Accepted { .. })
    }
}

pub struct HostService {
    inbox_dir: PathBuf,
}

impl HostService {
    pub fn new(inbox_dir: PathBuf) -> Result<Self> {
        if inbox_dir.as_os_str().is_empty() {
            bail!("Native host inbox directory cannot be empty");
        }

        Ok(Self { inbox_dir })
    }

    pub fn handle(&self, request: HostRequest) -> HostResponse {
        match request {
            HostRequest::Hello {
                protocols,
                extension_version,
                browser,
                capabilities,
            } => self.hello(protocols, extension_version, browser, capabilities),
            HostRequest::PrepareCapture {
                correlation_id,
                envelope,
            } => self.prepare_capture(correlation_id, *envelope),
        }
    }

    fn hello(
        &self,
        protocols: Vec<String>,
        extension_version: String,
        browser: HelloBrowser,
        capabilities: Vec<String>,
    ) -> HostResponse {
        if !protocols.iter().any(|protocol| protocol == PROTOCOL_NAME) {
            return HostResponse::rejected(String::new(), "APP_PROTOCOL_TOO_OLD", false);
        }

        if validate_hello(&protocols, &extension_version, &browser, &capabilities).is_err() {
            return HostResponse::invalid_request();
        }

        HostResponse::hello_ack()
    }

    fn prepare_capture(&self, correlation_id: String, envelope: DownloadEnvelope) -> HostResponse {
        if envelope.validate().is_err() {
            return HostResponse::rejected(correlation_id, "INVALID_REQUEST", false);
        }

        if envelope.request.method != "GET" {
            return HostResponse::rejected(correlation_id, "UNSUPPORTED_METHOD", false);
        }

        if envelope.request.body.is_some() {
            return HostResponse::rejected(correlation_id, "INVALID_REQUEST", false);
        }

        if envelope
            .media
            .as_ref()
            .is_some_and(|media| media.drm_detected)
        {
            return HostResponse::rejected(correlation_id, "DRM_PROTECTED", false);
        }

        match persist_idempotent(&self.inbox_dir, &envelope) {
            Ok(transfer_id) => HostResponse::accepted(correlation_id, transfer_id),
            Err(_) => HostResponse::rejected(correlation_id, "QUEUE_UNAVAILABLE", true),
        }
    }
}

fn validate_hello(
    protocols: &[String],
    extension_version: &str,
    browser: &HelloBrowser,
    capabilities: &[String],
) -> Result<()> {
    if protocols.is_empty() || protocols.len() > MAX_PROTOCOLS {
        bail!("Protocol negotiation is invalid");
    }

    for protocol in protocols {
        validate_text(protocol, 64, "advertised protocol")?;
    }

    validate_text(extension_version, 64, "extension version")?;
    validate_exact_member(&browser.family, BROWSER_FAMILIES, "browser family")?;
    validate_text(&browser.version, 128, "browser version")?;

    if capabilities.len() > MAX_CAPABILITIES {
        bail!("Too many advertised capabilities");
    }

    for capability in capabilities {
        validate_text(capability, 64, "capability")?;
    }

    Ok(())
}

fn validate_idempotency_key(idempotency_key: &str) -> Result<()> {
    let length = idempotency_key.chars().count();
    if !(32..=128).contains(&length)
        || idempotency_key
            .chars()
            .any(|character| character.is_control() || character.is_whitespace())
    {
        bail!("Idempotency key is invalid");
    }

    Ok(())
}

fn validate_timestamp(timestamp: &str) -> Result<()> {
    if !valid_rfc3339_timestamp(timestamp) {
        bail!("Creation timestamp is invalid");
    }

    Ok(())
}

fn valid_rfc3339_timestamp(timestamp: &str) -> bool {
    if !timestamp.is_ascii() {
        return false;
    }

    let Some((date, time)) = timestamp.split_once('T') else {
        return false;
    };

    valid_date(date) && valid_time_and_offset(time)
}

fn valid_date(date: &str) -> bool {
    let bytes = date.as_bytes();
    if bytes.len() != 10 || bytes[4] != b'-' || bytes[7] != b'-' {
        return false;
    }

    let Some(year) = parse_number(&bytes[0..4]) else {
        return false;
    };
    let Some(month) = parse_number(&bytes[5..7]) else {
        return false;
    };
    let Some(day) = parse_number(&bytes[8..10]) else {
        return false;
    };

    year > 0 && days_in_month(year, month).is_some_and(|days| day > 0 && day <= days)
}

fn valid_time_and_offset(time: &str) -> bool {
    let bytes = time.as_bytes();
    if bytes.len() < 9 || bytes[2] != b':' || bytes[5] != b':' {
        return false;
    }

    let Some(hour) = parse_number(&bytes[0..2]) else {
        return false;
    };
    let Some(minute) = parse_number(&bytes[3..5]) else {
        return false;
    };
    let Some(second) = parse_number(&bytes[6..8]) else {
        return false;
    };
    // The temporary PyQt inbox parser uses Python's datetime parser, which
    // deliberately rejects leap seconds.  Keep the host's acceptance set no
    // broader than the consumer's so an ACK never publishes a quarantined
    // envelope.
    if hour > 23 || minute > 59 || second > 59 {
        return false;
    }

    let Some(offset_start) = bytes
        .iter()
        .enumerate()
        .skip(8)
        .find_map(|(index, byte)| matches!(byte, b'Z' | b'+' | b'-').then_some(index))
    else {
        return false;
    };
    let fraction = &bytes[8..offset_start];
    if !fraction.is_empty()
        && (fraction[0] != b'.'
            || fraction.len() == 1
            || !fraction[1..].iter().all(u8::is_ascii_digit))
    {
        return false;
    }

    valid_offset(&bytes[offset_start..])
}

fn valid_offset(offset: &[u8]) -> bool {
    if offset == b"Z" {
        return true;
    }

    if offset.len() != 6 || !matches!(offset[0], b'+' | b'-') || offset[3] != b':' {
        return false;
    }

    matches!(
        (parse_number(&offset[1..3]), parse_number(&offset[4..6])),
        (Some(hours), Some(minutes)) if hours <= 23 && minutes <= 59
    )
}

fn parse_number(bytes: &[u8]) -> Option<u16> {
    if !bytes.iter().all(u8::is_ascii_digit) {
        return None;
    }

    Some(
        bytes
            .iter()
            .fold(0, |number, digit| number * 10 + u16::from(digit - b'0')),
    )
}

fn days_in_month(year: u16, month: u16) -> Option<u16> {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => Some(31),
        4 | 6 | 9 | 11 => Some(30),
        2 if year.is_multiple_of(4) && (!year.is_multiple_of(100) || year.is_multiple_of(400)) => {
            Some(29)
        }
        2 => Some(28),
        _ => None,
    }
}

fn validate_source(source: &str) -> Result<()> {
    validate_exact_member(source, REQUEST_SOURCES, "request source")
}

fn validate_http_url(url: &str, field: &str) -> Result<()> {
    if url.len() > MAX_URL_BYTES
        || url
            .chars()
            .any(|character| character.is_control() || character.is_whitespace())
    {
        bail!("{field} is invalid");
    }

    let parsed = Url::parse(url).map_err(|_| anyhow::anyhow!("{field} is invalid"))?;
    if !matches!(parsed.scheme(), "http" | "https") || parsed.host_str().is_none() {
        bail!("{field} must be an HTTP or HTTPS URL");
    }

    Ok(())
}

fn validate_optional_http_url(url: &Option<String>, field: &str) -> Result<()> {
    if let Some(url) = url {
        validate_http_url(url, field)?;
    }

    Ok(())
}

fn validate_headers(headers: &HashMap<String, String>) -> Result<()> {
    if headers.len() > MAX_HEADER_COUNT {
        bail!("Too many request headers");
    }

    let mut total_bytes = 0;
    let mut header_names = HashSet::new();
    for (name, value) in headers {
        total_bytes += name.len() + value.len();
        if total_bytes > MAX_HEADER_BYTES || !valid_header_name(name) || contains_control(value) {
            bail!("Request headers are invalid");
        }
        if !header_names.insert(name.to_ascii_lowercase()) {
            bail!("Request headers contain duplicates");
        }
    }

    Ok(())
}

fn valid_header_name(name: &str) -> bool {
    !name.is_empty()
        && name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&byte))
}

fn validate_optional_text(value: &Option<String>, maximum: usize, field: &str) -> Result<()> {
    if let Some(value) = value {
        validate_text(value, maximum, field)?;
    }

    Ok(())
}

fn validate_text(value: &str, maximum: usize, field: &str) -> Result<()> {
    if value.is_empty() || value.len() > maximum || contains_control(value) {
        bail!("{field} is invalid");
    }

    Ok(())
}

fn validate_optional_bytes(value: &Option<String>, maximum: usize, field: &str) -> Result<()> {
    if value.as_ref().is_some_and(|value| value.len() > maximum) {
        bail!("{field} exceeds its limit");
    }

    Ok(())
}

fn validate_optional_cookie_header(cookie_header: &Option<String>) -> Result<()> {
    let Some(cookie_header) = cookie_header else {
        return Ok(());
    };

    if cookie_header.len() > MAX_COOKIE_BYTES || contains_control(cookie_header) {
        bail!("Cookie header is invalid");
    }

    Ok(())
}

fn validate_exact_value(value: &str, expected: &str, field: &str) -> Result<()> {
    if value != expected {
        bail!("{field} is unsupported");
    }

    Ok(())
}

fn validate_exact_member(value: &str, allowed: &[&str], field: &str) -> Result<()> {
    if !allowed.contains(&value) {
        bail!("{field} is unsupported");
    }

    Ok(())
}

fn contains_control(value: &str) -> bool {
    value.chars().any(char::is_control)
}

#[cfg(test)]
mod tests {
    use super::{
        BrowserInfo, DownloadEnvelope, FileInfo, HostRequest, HostResponse, HostService, MediaInfo,
        RequestInfo,
    };
    use std::fs;
    use std::path::{Path, PathBuf};
    use uuid::Uuid;

    struct TemporaryInbox {
        path: PathBuf,
    }

    impl TemporaryInbox {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!("barq-protocol-test-{}", Uuid::new_v4()));
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

    fn envelope() -> DownloadEnvelope {
        DownloadEnvelope {
            protocol: "barq.browser.v1".to_string(),
            request_id: Uuid::new_v4(),
            idempotency_key: "a".repeat(32),
            created_at: "2026-08-08T12:00:00Z".to_string(),
            source: "context-menu".to_string(),
            request: RequestInfo {
                url: "https://example.com/archive.zip".to_string(),
                final_url: None,
                method: "GET".to_string(),
                referrer: Some("https://example.com/downloads".to_string()),
                page_url: Some("https://example.com/page".to_string()),
                initiator: Some("https://example.com".to_string()),
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

    fn assert_rejected(response: HostResponse, expected_code: &str) {
        match response {
            HostResponse::Rejected { code, .. } => assert_eq!(code, expected_code),
            _ => panic!("host response should be rejected"),
        }
    }

    #[test]
    fn invalid_envelope_is_rejected_before_persistence() {
        let inbox = TemporaryInbox::new();
        let service =
            HostService::new(inbox.path().to_path_buf()).expect("inbox path should be valid");
        let mut invalid_envelope = envelope();
        invalid_envelope.request.url = "file:///tmp/archive.zip".to_string();

        let response = service.handle(HostRequest::PrepareCapture {
            correlation_id: Uuid::new_v4().to_string(),
            envelope: Box::new(invalid_envelope),
        });

        assert_rejected(response, "INVALID_REQUEST");
        assert_eq!(
            fs::read_dir(inbox.path())
                .expect("inbox should be readable")
                .count(),
            0
        );
    }

    #[test]
    fn malformed_ipv6_url_is_rejected_before_persistence() {
        let inbox = TemporaryInbox::new();
        let service =
            HostService::new(inbox.path().to_path_buf()).expect("inbox path should be valid");
        let mut invalid_envelope = envelope();
        invalid_envelope.request.url = "https://[::1".to_string();

        let response = service.handle(HostRequest::PrepareCapture {
            correlation_id: Uuid::new_v4().to_string(),
            envelope: Box::new(invalid_envelope),
        });

        assert_rejected(response, "INVALID_REQUEST");
        assert_eq!(
            fs::read_dir(inbox.path())
                .expect("inbox should be readable")
                .count(),
            0
        );
    }

    #[test]
    fn invalid_calendar_timestamp_is_rejected() {
        let mut invalid_envelope = envelope();
        invalid_envelope.created_at = "2025-02-29T12:00:00Z".to_string();

        assert!(invalid_envelope.validate().is_err());
    }

    #[test]
    fn year_zero_timestamp_is_rejected_to_match_the_desktop_consumer() {
        let mut invalid_envelope = envelope();
        invalid_envelope.created_at = "0000-01-01T12:00:00Z".to_string();

        assert!(invalid_envelope.validate().is_err());
    }

    #[test]
    fn leap_second_timestamp_is_rejected_to_match_the_desktop_consumer() {
        let mut invalid_envelope = envelope();
        invalid_envelope.created_at = "2026-08-08T12:00:60Z".to_string();

        assert!(invalid_envelope.validate().is_err());
    }

    #[test]
    fn control_bearing_cookie_is_rejected_before_persistence() {
        let inbox = TemporaryInbox::new();
        let service =
            HostService::new(inbox.path().to_path_buf()).expect("inbox path should be valid");
        let mut invalid_envelope = envelope();
        invalid_envelope.request.cookie_header = Some("session=abc\r\nX-Injected: yes".to_string());

        let response = service.handle(HostRequest::PrepareCapture {
            correlation_id: Uuid::new_v4().to_string(),
            envelope: Box::new(invalid_envelope),
        });

        assert_rejected(response, "INVALID_REQUEST");
        assert_eq!(
            fs::read_dir(inbox.path())
                .expect("inbox should be readable")
                .count(),
            0
        );
    }

    #[test]
    fn case_insensitive_duplicate_headers_are_rejected_before_persistence() {
        let inbox = TemporaryInbox::new();
        let service =
            HostService::new(inbox.path().to_path_buf()).expect("inbox path should be valid");
        let mut invalid_envelope = envelope();
        invalid_envelope
            .request
            .headers
            .insert("Accept".to_string(), "application/octet-stream".to_string());
        invalid_envelope
            .request
            .headers
            .insert("accept".to_string(), "application/zip".to_string());

        let response = service.handle(HostRequest::PrepareCapture {
            correlation_id: Uuid::new_v4().to_string(),
            envelope: Box::new(invalid_envelope),
        });

        assert_rejected(response, "INVALID_REQUEST");
        assert_eq!(
            fs::read_dir(inbox.path())
                .expect("inbox should be readable")
                .count(),
            0
        );
    }

    #[test]
    fn non_get_request_is_rejected_before_persistence() {
        let inbox = TemporaryInbox::new();
        let service =
            HostService::new(inbox.path().to_path_buf()).expect("inbox path should be valid");
        let mut post_envelope = envelope();
        post_envelope.request.method = "POST".to_string();

        let response = service.handle(HostRequest::PrepareCapture {
            correlation_id: Uuid::new_v4().to_string(),
            envelope: Box::new(post_envelope),
        });

        assert_rejected(response, "UNSUPPORTED_METHOD");
        assert_eq!(
            fs::read_dir(inbox.path())
                .expect("inbox should be readable")
                .count(),
            0
        );
    }

    #[test]
    fn drm_media_is_rejected_without_writing_an_envelope() {
        let inbox = TemporaryInbox::new();
        let service =
            HostService::new(inbox.path().to_path_buf()).expect("inbox path should be valid");
        let mut drm_envelope = envelope();
        drm_envelope.media = Some(MediaInfo {
            page_title: Some("Protected video".to_string()),
            candidates: None,
            drm_detected: true,
        });

        let response = service.handle(HostRequest::PrepareCapture {
            correlation_id: Uuid::new_v4().to_string(),
            envelope: Box::new(drm_envelope),
        });

        assert_rejected(response, "DRM_PROTECTED");
        assert_eq!(
            fs::read_dir(inbox.path())
                .expect("inbox should be readable")
                .count(),
            0
        );
    }
}
