//! A blocking, single-stream HTTP/HTTPS transport backed by libcurl.
//!
//! This crate deliberately does **not** implement resume, range downloads, or
//! parallel connections. It is the M1 building block for a daemon that will
//! own those policies later. Every download here is a new, full `GET` request
//! written to one sink.

use std::{
    cell::RefCell,
    fs::OpenOptions,
    io::{self, Write},
    path::Path,
    time::Duration,
};

use curl::easy::Easy;
use thiserror::Error;
use url::Url;

const DEFAULT_CONNECT_TIMEOUT: Duration = Duration::from_secs(15);
const DEFAULT_LOW_SPEED_LIMIT_BYTES_PER_SECOND: u32 = 1;
const DEFAULT_LOW_SPEED_TIMEOUT: Duration = Duration::from_secs(60);
const DEFAULT_MAX_REDIRECTS: u32 = 10;
const DEFAULT_MAX_HEADER_BYTES: usize = 128 * 1024;
const DEFAULT_METADATA_GET_MAX_BODY_BYTES: u64 = 64 * 1024;
const USER_AGENT: &str = "Barq-Engine/0.1";

/// Runtime libcurl details for engine diagnostics.
pub fn linked_version() -> &'static str {
    curl::Version::num()
}

/// Transport-wide safety and liveness limits.
///
/// `transfer_timeout` is intentionally optional: a real download can take a
/// long time, while libcurl's low-speed timeout still prevents a stuck peer
/// from blocking forever. `max_body_bytes` is opt-in for full downloads.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TransportOptions {
    pub connect_timeout: Duration,
    pub transfer_timeout: Option<Duration>,
    pub low_speed_limit_bytes_per_second: u32,
    pub low_speed_timeout: Duration,
    pub max_redirects: u32,
    pub max_header_bytes: usize,
    pub max_body_bytes: Option<u64>,
    pub metadata_get_max_body_bytes: u64,
}

impl Default for TransportOptions {
    fn default() -> Self {
        Self {
            connect_timeout: DEFAULT_CONNECT_TIMEOUT,
            transfer_timeout: None,
            low_speed_limit_bytes_per_second: DEFAULT_LOW_SPEED_LIMIT_BYTES_PER_SECOND,
            low_speed_timeout: DEFAULT_LOW_SPEED_TIMEOUT,
            max_redirects: DEFAULT_MAX_REDIRECTS,
            max_header_bytes: DEFAULT_MAX_HEADER_BYTES,
            max_body_bytes: None,
            metadata_get_max_body_bytes: DEFAULT_METADATA_GET_MAX_BODY_BYTES,
        }
    }
}

/// The HTTP method used to inspect a remote resource.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MetadataMethod {
    /// A body-less HTTP `HEAD` request.
    Head,
    /// A bounded HTTP `GET` probe. It requests byte `0-0` and discards it.
    Get,
}

/// Response information from the final HTTP response after redirects.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResponseMetadata {
    pub requested_url: String,
    pub effective_url: String,
    pub status_code: u32,
    /// The full object length when known.
    ///
    /// For a ranged metadata `GET`, this uses the total from `Content-Range`
    /// instead of the one-byte `Content-Length`.
    pub content_length: Option<u64>,
    pub content_type: Option<String>,
    pub etag: Option<String>,
    pub last_modified: Option<String>,
    pub accepts_ranges: bool,
    pub redirect_count: u32,
}

/// The result of a complete, single-stream download.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DownloadResponse {
    pub metadata: ResponseMetadata,
    pub bytes_written: u64,
}

#[derive(Debug, Error)]
pub enum TransportError {
    #[error("invalid URL `{url}`: {source}")]
    InvalidUrl {
        url: String,
        #[source]
        source: url::ParseError,
    },
    #[error("only absolute HTTP/HTTPS URLs are supported, got `{url}`")]
    UnsupportedUrlScheme { url: String },
    #[error("invalid transport options: {message}")]
    InvalidOptions { message: &'static str },
    #[error("libcurl failed: {0}")]
    Curl(#[from] curl::Error),
    #[error("failed to write the destination: {0}")]
    Io(#[from] io::Error),
    #[error("response headers exceeded the configured {limit} byte limit")]
    HeaderTooLarge { limit: usize },
    #[error("response body exceeded the configured {limit} byte limit")]
    BodyTooLarge { limit: u64 },
    #[error("response `{url}` returned HTTP {status_code}")]
    HttpStatus { url: String, status_code: u32 },
    #[error("download response `{url}` unexpectedly returned HTTP 206 without a range request")]
    UnexpectedPartialContent { url: String },
    #[error("redirect response `{url}` did not include a Location header")]
    MissingRedirectLocation { url: String },
    #[error("redirect limit of {limit} was exceeded while requesting `{url}`")]
    RedirectLimitExceeded { url: String, limit: u32 },
    #[error("libcurl did not provide an HTTP status line for `{url}`")]
    MissingResponseStatus { url: String },
    #[error(
        "header status {header_status} did not match libcurl status {curl_status} for `{url}`"
    )]
    ResponseStatusMismatch {
        url: String,
        header_status: u32,
        curl_status: u32,
    },
}

/// A synchronous libcurl transport for exactly one response body at a time.
#[derive(Debug, Clone)]
pub struct SingleStreamTransport {
    options: TransportOptions,
}

impl Default for SingleStreamTransport {
    fn default() -> Self {
        Self::new(TransportOptions::default())
            .expect("the built-in single-stream transport options are valid")
    }
}

impl SingleStreamTransport {
    pub fn new(options: TransportOptions) -> Result<Self, TransportError> {
        validate_options(&options)?;
        Ok(Self { options })
    }

    pub fn options(&self) -> &TransportOptions {
        &self.options
    }

    /// Fetch metadata with a `HEAD` or bounded `GET` probe.
    ///
    /// Redirects are followed manually so every redirect target is verified as
    /// HTTP/HTTPS before libcurl contacts it.
    pub fn metadata(
        &self,
        url: &str,
        method: MetadataMethod,
    ) -> Result<ResponseMetadata, TransportError> {
        let requested_url = parse_http_url(url)?;
        let mut current_url = requested_url.clone();
        let mut discard = DiscardWriter;

        for redirect_count in 0..=self.options.max_redirects {
            let response = self.perform(
                &current_url,
                RequestKind::Metadata(method),
                &mut discard,
                Some(self.options.metadata_get_max_body_bytes),
            )?;

            if is_redirect(response.status_code) {
                current_url = next_redirect_url(&current_url, &response)?;
                if redirect_count == self.options.max_redirects {
                    return Err(TransportError::RedirectLimitExceeded {
                        url: current_url.to_string(),
                        limit: self.options.max_redirects,
                    });
                }
                continue;
            }

            validate_metadata_status(&response)?;
            return Ok(response.metadata(requested_url.as_str(), redirect_count));
        }

        unreachable!("the redirect loop always returns or errors")
    }

    /// Download a new, full HTTP response into one caller-provided sink.
    ///
    /// The caller owns destination lifecycle. This function neither resumes a
    /// partial sink nor sends a `Range` or `If-Range` header. It writes only a
    /// successful final response; redirect and error bodies are discarded.
    pub fn download_to_writer<W: Write>(
        &self,
        url: &str,
        sink: &mut W,
    ) -> Result<DownloadResponse, TransportError> {
        let requested_url = parse_http_url(url)?;
        let mut current_url = requested_url.clone();

        for redirect_count in 0..=self.options.max_redirects {
            let response = self.perform(
                &current_url,
                RequestKind::Download,
                sink,
                self.options.max_body_bytes,
            )?;

            if is_redirect(response.status_code) {
                current_url = next_redirect_url(&current_url, &response)?;
                if redirect_count == self.options.max_redirects {
                    return Err(TransportError::RedirectLimitExceeded {
                        url: current_url.to_string(),
                        limit: self.options.max_redirects,
                    });
                }
                continue;
            }

            validate_download_status(&response)?;
            return Ok(DownloadResponse {
                metadata: response.metadata(requested_url.as_str(), redirect_count),
                bytes_written: response.bytes_written,
            });
        }

        unreachable!("the redirect loop always returns or errors")
    }

    /// Download into a path after truncating or creating it.
    ///
    /// Future daemon code should pass a staging path here, then atomically
    /// promote it after its own integrity and state checks. This transport does
    /// not provide final-file replacement or resume semantics.
    pub fn download_to_path(
        &self,
        url: &str,
        destination: impl AsRef<Path>,
    ) -> Result<DownloadResponse, TransportError> {
        // Validate before opening a caller-owned path so an obviously invalid
        // request cannot truncate it.
        parse_http_url(url)?;
        let mut file = OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .open(destination)?;
        self.download_to_writer(url, &mut file)
    }

    fn perform<W: Write>(
        &self,
        url: &Url,
        kind: RequestKind,
        sink: &mut W,
        body_limit: Option<u64>,
    ) -> Result<RawResponse, TransportError> {
        let mut easy = self.new_easy(url, kind)?;
        let headers = RefCell::new(HeaderCollector::new(self.options.max_header_bytes));
        let mut bytes_written = 0_u64;
        let mut body_bytes_received = 0_u64;
        let mut sink_failure = None;

        let transfer_result = {
            let mut transfer = easy.transfer();
            transfer.header_function(|line| headers.borrow_mut().push(line))?;
            transfer.write_function(|data| {
                let incoming = u64::try_from(data.len()).unwrap_or(u64::MAX);
                let next_received = body_bytes_received.saturating_add(incoming);
                if let Some(limit) = body_limit {
                    if next_received > limit {
                        sink_failure = Some(CallbackFailure::BodyTooLarge { limit });
                        // Returning a short write aborts this blocking easy
                        // transfer. `WriteError::Pause` would leave it
                        // suspended forever because this transport has no
                        // async unpause path.
                        return Ok(0);
                    }
                }
                body_bytes_received = next_received;

                if !kind.writes_response_body(headers.borrow().status_code()) {
                    return Ok(data.len());
                }

                let next_written = bytes_written.saturating_add(incoming);

                if let Err(error) = sink.write_all(data) {
                    sink_failure = Some(CallbackFailure::Io(error));
                    return Ok(0);
                }

                bytes_written = next_written;
                Ok(data.len())
            })?;
            transfer.perform()
        };

        if let Some(error) = headers.borrow().error() {
            return Err(error);
        }
        if let Some(error) = sink_failure {
            return Err(error.into_transport_error());
        }
        transfer_result?;

        let curl_status = easy.response_code()?;
        let header = headers.into_inner().finish(url.as_str(), curl_status)?;
        let effective_url = easy.effective_url()?.unwrap_or(url.as_str()).to_owned();
        parse_http_url(&effective_url)?;

        Ok(RawResponse {
            effective_url,
            status_code: curl_status,
            headers: header,
            bytes_written,
        })
    }

    fn new_easy(&self, url: &Url, kind: RequestKind) -> Result<Easy, TransportError> {
        let mut easy = Easy::new();
        easy.url(url.as_str())?;
        // Redirects are intentionally handled above so redirect schemes are
        // checked before a connection is opened to their targets.
        easy.follow_location(false)?;
        easy.connect_timeout(self.options.connect_timeout)?;
        if let Some(timeout) = self.options.transfer_timeout {
            easy.timeout(timeout)?;
        }
        easy.low_speed_limit(self.options.low_speed_limit_bytes_per_second)?;
        easy.low_speed_time(self.options.low_speed_timeout)?;
        easy.useragent(USER_AGENT)?;
        // Persist the server's bytes, not a transparently decompressed variant.
        easy.accept_encoding("identity")?;
        easy.http_content_decoding(false)?;

        match kind {
            RequestKind::Metadata(MetadataMethod::Head) => easy.nobody(true)?,
            RequestKind::Metadata(MetadataMethod::Get) => {
                easy.get(true)?;
                // A GET metadata probe is bounded to one byte. Its full size,
                // when supplied, is read from Content-Range.
                easy.range("0-0")?;
            }
            RequestKind::Download => easy.get(true)?,
        }

        Ok(easy)
    }
}

#[derive(Debug, Clone, Copy)]
enum RequestKind {
    Metadata(MetadataMethod),
    Download,
}

impl RequestKind {
    fn writes_response_body(self, status_code: Option<u32>) -> bool {
        matches!(self, Self::Download)
            && status_code.is_some_and(is_success_status)
            && status_code != Some(206)
    }
}

#[derive(Debug)]
enum CallbackFailure {
    BodyTooLarge { limit: u64 },
    Io(io::Error),
}

impl CallbackFailure {
    fn into_transport_error(self) -> TransportError {
        match self {
            Self::BodyTooLarge { limit } => TransportError::BodyTooLarge { limit },
            Self::Io(error) => TransportError::Io(error),
        }
    }
}

#[derive(Debug)]
struct RawResponse {
    effective_url: String,
    status_code: u32,
    headers: ResponseHeaders,
    bytes_written: u64,
}

impl RawResponse {
    fn metadata(&self, requested_url: &str, redirect_count: u32) -> ResponseMetadata {
        ResponseMetadata {
            requested_url: requested_url.to_owned(),
            effective_url: self.effective_url.clone(),
            status_code: self.status_code,
            content_length: self.headers.total_content_length(),
            content_type: self.headers.content_type.clone(),
            etag: self.headers.etag.clone(),
            last_modified: self.headers.last_modified.clone(),
            accepts_ranges: self.headers.accepts_ranges,
            redirect_count,
        }
    }
}

#[derive(Debug, Default)]
struct ResponseHeaders {
    status_code: u32,
    content_length: Option<u64>,
    content_range: Option<String>,
    content_type: Option<String>,
    etag: Option<String>,
    last_modified: Option<String>,
    location: Option<String>,
    accepts_ranges: bool,
}

impl ResponseHeaders {
    fn total_content_length(&self) -> Option<u64> {
        content_range_total(self.content_range.as_deref()).or(self.content_length)
    }
}

#[derive(Debug)]
struct HeaderCollector {
    current: Option<ResponseHeaders>,
    in_headers: bool,
    header_bytes_in_response: usize,
    max_header_bytes: usize,
    too_large: bool,
}

impl HeaderCollector {
    fn new(max_header_bytes: usize) -> Self {
        Self {
            current: None,
            in_headers: false,
            header_bytes_in_response: 0,
            max_header_bytes,
            too_large: false,
        }
    }

    fn push(&mut self, bytes: &[u8]) -> bool {
        let line = String::from_utf8_lossy(bytes);
        let trimmed = line.trim_end_matches(['\r', '\n']);

        if let Some(status_code) = parse_status_line(trimmed) {
            self.current = Some(ResponseHeaders {
                status_code,
                ..ResponseHeaders::default()
            });
            self.in_headers = true;
            self.header_bytes_in_response = bytes.len();
            return self.check_header_limit();
        }

        if !self.in_headers {
            // Ignore trailers; they are delivered through the same callback.
            return true;
        }

        self.header_bytes_in_response = self.header_bytes_in_response.saturating_add(bytes.len());
        if !self.check_header_limit() {
            return false;
        }

        if trimmed.is_empty() {
            self.in_headers = false;
            return true;
        }

        let Some((name, value)) = trimmed.split_once(':') else {
            return true;
        };
        let value = value.trim().to_owned();
        let Some(headers) = self.current.as_mut() else {
            return true;
        };

        match name.trim().to_ascii_lowercase().as_str() {
            "content-length" => headers.content_length = value.parse().ok(),
            "content-range" => headers.content_range = Some(value),
            "content-type" => headers.content_type = Some(value),
            "etag" => headers.etag = Some(value),
            "last-modified" => headers.last_modified = Some(value),
            "location" => headers.location = Some(value),
            "accept-ranges" => headers.accepts_ranges = value.eq_ignore_ascii_case("bytes"),
            _ => {}
        }

        true
    }

    fn status_code(&self) -> Option<u32> {
        self.current.as_ref().map(|headers| headers.status_code)
    }

    fn error(&self) -> Option<TransportError> {
        self.too_large.then_some(TransportError::HeaderTooLarge {
            limit: self.max_header_bytes,
        })
    }

    fn finish(self, url: &str, curl_status: u32) -> Result<ResponseHeaders, TransportError> {
        let headers = self
            .current
            .ok_or_else(|| TransportError::MissingResponseStatus {
                url: url.to_owned(),
            })?;

        if headers.status_code != curl_status {
            return Err(TransportError::ResponseStatusMismatch {
                url: url.to_owned(),
                header_status: headers.status_code,
                curl_status,
            });
        }
        Ok(headers)
    }

    fn check_header_limit(&mut self) -> bool {
        if self.header_bytes_in_response > self.max_header_bytes {
            self.too_large = true;
            false
        } else {
            true
        }
    }
}

struct DiscardWriter;

impl Write for DiscardWriter {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        Ok(buffer.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn validate_options(options: &TransportOptions) -> Result<(), TransportError> {
    if options.connect_timeout.is_zero() {
        return Err(TransportError::InvalidOptions {
            message: "connect_timeout must be greater than zero",
        });
    }
    if options
        .transfer_timeout
        .is_some_and(|timeout| timeout.is_zero())
    {
        return Err(TransportError::InvalidOptions {
            message: "transfer_timeout must be greater than zero when configured",
        });
    }
    if options.low_speed_timeout.is_zero() {
        return Err(TransportError::InvalidOptions {
            message: "low_speed_timeout must be greater than zero",
        });
    }
    if options.low_speed_limit_bytes_per_second == 0 {
        return Err(TransportError::InvalidOptions {
            message: "low_speed_limit_bytes_per_second must be greater than zero",
        });
    }
    if options.max_header_bytes == 0 {
        return Err(TransportError::InvalidOptions {
            message: "max_header_bytes must be greater than zero",
        });
    }
    if options.metadata_get_max_body_bytes == 0 {
        return Err(TransportError::InvalidOptions {
            message: "metadata_get_max_body_bytes must be greater than zero",
        });
    }
    Ok(())
}

fn parse_http_url(value: &str) -> Result<Url, TransportError> {
    let url = Url::parse(value).map_err(|source| TransportError::InvalidUrl {
        url: value.to_owned(),
        source,
    })?;

    if !matches!(url.scheme(), "http" | "https") || url.host().is_none() {
        return Err(TransportError::UnsupportedUrlScheme {
            url: value.to_owned(),
        });
    }
    Ok(url)
}

fn next_redirect_url(current_url: &Url, response: &RawResponse) -> Result<Url, TransportError> {
    let location = response.headers.location.as_deref().ok_or_else(|| {
        TransportError::MissingRedirectLocation {
            url: response.effective_url.clone(),
        }
    })?;
    let next = current_url
        .join(location)
        .map_err(|source| TransportError::InvalidUrl {
            url: location.to_owned(),
            source,
        })?;
    parse_http_url(next.as_str())
}

fn validate_metadata_status(response: &RawResponse) -> Result<(), TransportError> {
    if is_success_status(response.status_code) {
        Ok(())
    } else {
        Err(TransportError::HttpStatus {
            url: response.effective_url.clone(),
            status_code: response.status_code,
        })
    }
}

fn validate_download_status(response: &RawResponse) -> Result<(), TransportError> {
    if response.status_code == 206 {
        return Err(TransportError::UnexpectedPartialContent {
            url: response.effective_url.clone(),
        });
    }
    validate_metadata_status(response)
}

fn is_success_status(status_code: u32) -> bool {
    (200..300).contains(&status_code)
}

fn is_redirect(status_code: u32) -> bool {
    matches!(status_code, 301 | 302 | 303 | 307 | 308)
}

fn parse_status_line(line: &str) -> Option<u32> {
    if !line.starts_with("HTTP/") {
        return None;
    }
    line.split_whitespace().nth(1)?.parse().ok()
}

fn content_range_total(value: Option<&str>) -> Option<u64> {
    let value = value?.trim();
    let (_, total) = value.rsplit_once('/')?;
    if total == "*" {
        None
    } else {
        total.parse().ok()
    }
}

#[cfg(test)]
mod tests {
    use std::{
        io::{Read, Write},
        net::{Shutdown, TcpListener, TcpStream},
        sync::{Arc, Mutex},
        thread::{self, JoinHandle},
        time::{Duration, Instant},
    };

    use super::*;

    struct LocalServer {
        url: String,
        requests: Arc<Mutex<Vec<String>>>,
        handle: Option<JoinHandle<()>>,
    }

    impl LocalServer {
        fn start(responses: Vec<String>) -> Self {
            let listener = TcpListener::bind("127.0.0.1:0").expect("bind local test server");
            listener
                .set_nonblocking(true)
                .expect("configure local test server");
            let address = listener.local_addr().expect("read local test address");
            let requests = Arc::new(Mutex::new(Vec::new()));
            let requests_for_thread = Arc::clone(&requests);

            let handle = thread::spawn(move || {
                let deadline = Instant::now() + Duration::from_secs(5);
                for response in responses {
                    let mut stream = loop {
                        match listener.accept() {
                            Ok((stream, _)) => break stream,
                            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                                if Instant::now() >= deadline {
                                    return;
                                }
                                thread::sleep(Duration::from_millis(5));
                            }
                            Err(error) => panic!("accept local test connection: {error}"),
                        }
                    };
                    let request = read_http_request(&mut stream);
                    requests_for_thread
                        .lock()
                        .expect("lock request log")
                        .push(request);
                    stream
                        .write_all(response.as_bytes())
                        .expect("write local HTTP response");
                    stream.flush().expect("flush local HTTP response");
                    stream
                        .shutdown(Shutdown::Both)
                        .expect("close local response");
                }
            });

            Self {
                url: format!("http://{address}"),
                requests,
                handle: Some(handle),
            }
        }

        fn requests(mut self) -> Vec<String> {
            self.handle
                .take()
                .expect("test server thread exists")
                .join()
                .expect("test server thread did not panic");
            self.requests.lock().expect("lock request log").clone()
        }
    }

    impl Drop for LocalServer {
        fn drop(&mut self) {
            if let Some(handle) = self.handle.take() {
                let _ = handle.join();
            }
        }
    }

    #[test]
    fn linked_version_reports_the_runtime_library() {
        assert!(!linked_version().is_empty());
    }

    #[test]
    fn metadata_head_follows_only_http_redirects_and_keeps_final_headers() {
        let server = LocalServer::start(vec![
            response(302, "Found", &["Location: /artifact"], ""),
            response(
                200,
                "OK",
                &[
                    "Content-Length: 12",
                    "Content-Type: application/octet-stream",
                    "ETag: \"v1\"",
                    "Accept-Ranges: bytes",
                ],
                "",
            ),
        ]);
        let transport = SingleStreamTransport::default();

        let metadata = transport
            .metadata(&format!("{}/start", server.url), MetadataMethod::Head)
            .expect("metadata request succeeds");

        assert_eq!(metadata.status_code, 200);
        assert_eq!(metadata.content_length, Some(12));
        assert_eq!(
            metadata.content_type.as_deref(),
            Some("application/octet-stream")
        );
        assert_eq!(metadata.etag.as_deref(), Some("\"v1\""));
        assert!(metadata.accepts_ranges);
        assert_eq!(metadata.redirect_count, 1);
        assert!(metadata.effective_url.ends_with("/artifact"));

        let requests = server.requests();
        assert_eq!(requests.len(), 2);
        assert!(requests.iter().all(|request| request.starts_with("HEAD ")));
    }

    #[test]
    fn get_metadata_probe_uses_one_byte_range_and_reads_full_length() {
        let server = LocalServer::start(vec![response(
            206,
            "Partial Content",
            &["Content-Length: 1", "Content-Range: bytes 0-0/11"],
            "B",
        )]);
        let transport = SingleStreamTransport::default();

        let metadata = transport
            .metadata(&format!("{}/asset", server.url), MetadataMethod::Get)
            .expect("GET metadata request succeeds");

        assert_eq!(metadata.status_code, 206);
        assert_eq!(metadata.content_length, Some(11));
        let requests = server.requests();
        assert!(requests[0].starts_with("GET /asset HTTP/"));
        assert!(requests[0]
            .lines()
            .any(|line| line.eq_ignore_ascii_case("range: bytes=0-0")));
    }

    #[test]
    fn get_metadata_probe_is_bounded_when_a_server_ignores_range() {
        let server = LocalServer::start(vec![response(200, "OK", &["Content-Length: 3"], "too")]);
        let options = TransportOptions {
            metadata_get_max_body_bytes: 1,
            ..TransportOptions::default()
        };
        let transport = SingleStreamTransport::new(options).expect("valid transport options");

        let error = transport
            .metadata(&format!("{}/asset", server.url), MetadataMethod::Get)
            .expect_err("unbounded GET metadata response must fail");

        assert!(matches!(error, TransportError::BodyTooLarge { limit: 1 }));
        let _ = server.requests();
    }

    #[test]
    fn redirect_to_a_non_http_scheme_is_rejected_before_a_second_request() {
        let server = LocalServer::start(vec![response(
            302,
            "Found",
            &["Location: file:///not-a-download"],
            "",
        )]);
        let transport = SingleStreamTransport::default();

        let error = transport
            .metadata(&format!("{}/start", server.url), MetadataMethod::Head)
            .expect_err("non-HTTP redirect must fail");

        assert!(matches!(error, TransportError::UnsupportedUrlScheme { .. }));
        assert_eq!(server.requests().len(), 1);
    }

    #[test]
    fn download_follows_redirect_and_writes_only_the_final_success_body() {
        let server = LocalServer::start(vec![
            response(302, "Found", &["Location: /payload"], "ignored"),
            response(
                200,
                "OK",
                &["Content-Length: 11", "ETag: \"payload-v1\""],
                "barq-stream",
            ),
        ]);
        let transport = SingleStreamTransport::default();
        let mut sink = Vec::new();

        let result = transport
            .download_to_writer(&format!("{}/start", server.url), &mut sink)
            .expect("download succeeds");

        assert_eq!(sink, b"barq-stream");
        assert_eq!(result.bytes_written, 11);
        assert_eq!(result.metadata.etag.as_deref(), Some("\"payload-v1\""));
        assert_eq!(result.metadata.redirect_count, 1);
        let requests = server.requests();
        assert!(requests.iter().all(|request| request.starts_with("GET ")));
        assert!(requests
            .iter()
            .all(|request| !request.lines().any(|line| line.starts_with("Range:"))));
    }

    #[test]
    fn error_and_partial_responses_do_not_write_to_the_sink() {
        let server = LocalServer::start(vec![response(404, "Not Found", &[], "not found")]);
        let transport = SingleStreamTransport::default();
        let mut sink = Vec::new();

        let error = transport
            .download_to_writer(&format!("{}/missing", server.url), &mut sink)
            .expect_err("404 must fail");

        assert!(matches!(
            error,
            TransportError::HttpStatus {
                status_code: 404,
                ..
            }
        ));
        assert!(sink.is_empty());
        let _ = server.requests();

        let partial_server = LocalServer::start(vec![response(
            206,
            "Partial Content",
            &["Content-Range: bytes 3-4/5"],
            "q!",
        )]);
        let mut partial_sink = Vec::new();
        let error = transport
            .download_to_writer(
                &format!("{}/partial", partial_server.url),
                &mut partial_sink,
            )
            .expect_err("unexpected 206 must fail");
        assert!(matches!(
            error,
            TransportError::UnexpectedPartialContent { .. }
        ));
        assert!(partial_sink.is_empty());
        let _ = partial_server.requests();
    }

    #[test]
    fn header_parser_ignores_trailers_and_enforces_the_limit() {
        let mut collector = HeaderCollector::new(40);
        assert!(collector.push(b"HTTP/1.1 200 OK\r\n"));
        assert!(collector.push(b"ETag: \"before\"\r\n"));
        assert!(collector.push(b"\r\n"));
        assert!(collector.push(b"ETag: \"trailer\"\r\n"));
        let headers = collector.finish("http://example.test", 200).unwrap();
        assert_eq!(headers.etag.as_deref(), Some("\"before\""));

        let mut limited = HeaderCollector::new(8);
        assert!(!limited.push(b"HTTP/1.1 200 OK\r\n"));
        assert!(matches!(
            limited.error(),
            Some(TransportError::HeaderTooLarge { limit: 8 })
        ));
    }

    #[test]
    fn zero_liveness_or_header_limits_are_rejected() {
        let invalid_connect = TransportOptions {
            connect_timeout: Duration::ZERO,
            ..TransportOptions::default()
        };
        assert!(matches!(
            SingleStreamTransport::new(invalid_connect),
            Err(TransportError::InvalidOptions { .. })
        ));

        let invalid_low_speed = TransportOptions {
            low_speed_limit_bytes_per_second: 0,
            ..TransportOptions::default()
        };
        assert!(matches!(
            SingleStreamTransport::new(invalid_low_speed),
            Err(TransportError::InvalidOptions { .. })
        ));
    }

    fn response(status: u16, reason: &str, headers: &[&str], body: &str) -> String {
        let mut response = format!("HTTP/1.1 {status} {reason}\r\n");
        for header in headers {
            response.push_str(header);
            response.push_str("\r\n");
        }
        response.push_str("Connection: close\r\n\r\n");
        response.push_str(body);
        response
    }

    fn read_http_request(stream: &mut TcpStream) -> String {
        stream
            .set_read_timeout(Some(Duration::from_secs(2)))
            .expect("set local request timeout");
        let mut request = Vec::new();
        let mut chunk = [0_u8; 1024];
        while !request.windows(4).any(|window| window == b"\r\n\r\n") {
            let count = stream.read(&mut chunk).expect("read local request");
            assert!(count > 0, "local client closed request before headers");
            request.extend_from_slice(&chunk[..count]);
        }
        String::from_utf8(request).expect("local request is HTTP text")
    }
}
