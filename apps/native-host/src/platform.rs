use anyhow::{bail, Context, Result};
use std::collections::BTreeSet;
use std::env;
use std::path::{Path, PathBuf};

const ALLOWED_ORIGINS_ENV: &str = "BARQ_ALLOWED_ORIGINS";
const INBOX_DIRECTORY_ENV: &str = "BARQ_BROWSER_INBOX_DIR";
const CHROMIUM_EXTENSION_PREFIX: &str = "chrome-extension://";
const FIREFOX_EXTENSION_PREFIX: &str = "firefox-extension://";

#[derive(Clone, Debug)]
pub struct RuntimeConfig {
    allowed_origins: BTreeSet<String>,
    inbox_dir: PathBuf,
}

impl RuntimeConfig {
    pub fn allowed_origins(&self) -> &BTreeSet<String> {
        &self.allowed_origins
    }

    pub fn inbox_dir(&self) -> &Path {
        &self.inbox_dir
    }
}

pub fn load_runtime_config() -> Result<RuntimeConfig> {
    Ok(RuntimeConfig {
        allowed_origins: parse_allowed_origins(&configured_allowed_origins()?)?,
        inbox_dir: inbox_dir()?,
    })
}

fn configured_allowed_origins() -> Result<String> {
    if let Some(origins) = option_env!("BARQ_ALLOWED_ORIGINS") {
        return Ok(origins.to_owned());
    }

    env::var(ALLOWED_ORIGINS_ENV).with_context(|| {
        format!("{ALLOWED_ORIGINS_ENV} must contain packaging-generated extension origins")
    })
}

pub(crate) fn parse_allowed_origins(configured_origins: &str) -> Result<BTreeSet<String>> {
    let mut allowed_origins = BTreeSet::new();

    for configured_origin in configured_origins.split(',') {
        let configured_origin = configured_origin.trim();
        if configured_origin.is_empty() {
            bail!("Allowed origin configuration contains an empty entry");
        }
        allowed_origins.insert(normalize_configured_caller(configured_origin)?);
    }

    if allowed_origins.is_empty() {
        bail!("At least one extension origin must be configured");
    }

    Ok(allowed_origins)
}

pub fn verify_caller_origin(args: &[String], allowed_origins: &BTreeSet<String>) -> Result<()> {
    let first_argument = args
        .get(1)
        .context("Native host caller identity was not supplied")?;
    let caller_origin = if first_argument.starts_with(CHROMIUM_EXTENSION_PREFIX) {
        normalize_chromium_caller_origin(first_argument)
            .context("Native host Chromium caller origin is invalid")?
    } else {
        let extension_id = args
            .get(2)
            .context("Native host Firefox add-on ID was not supplied")?;
        normalize_firefox_extension_id(extension_id)
            .context("Native host Firefox add-on ID is invalid")?
    };

    if !allowed_origins.contains(&caller_origin) {
        bail!("Native host caller identity is not allowed");
    }

    Ok(())
}

fn normalize_configured_caller(caller: &str) -> Result<String> {
    if caller.starts_with(CHROMIUM_EXTENSION_PREFIX) {
        return normalize_chromium_extension_origin(caller);
    }
    if let Some(extension_id) = caller.strip_prefix(FIREFOX_EXTENSION_PREFIX) {
        return normalize_firefox_extension_id(extension_id);
    }

    bail!("Configured caller uses an unsupported scheme");
}

fn normalize_chromium_caller_origin(origin: &str) -> Result<String> {
    if !origin.ends_with('/') {
        bail!("Native host caller origin must use canonical form");
    }

    normalize_chromium_extension_origin(origin)
}

fn normalize_chromium_extension_origin(origin: &str) -> Result<String> {
    let authority = origin
        .strip_prefix(CHROMIUM_EXTENSION_PREFIX)
        .context("Chromium extension origin uses an unsupported scheme")?;

    let extension_id = authority.strip_suffix('/').unwrap_or(authority);
    if extension_id.is_empty()
        || extension_id.contains('/')
        || !extension_id
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || matches!(character, '-' | '_'))
    {
        bail!("Extension origin has an invalid authority");
    }

    Ok(format!("{CHROMIUM_EXTENSION_PREFIX}{extension_id}/"))
}

fn normalize_firefox_extension_id(extension_id: &str) -> Result<String> {
    if extension_id.is_empty()
        || extension_id.len() > 255
        || extension_id.contains('/')
        || extension_id
            .chars()
            .any(|character| character.is_control() || character.is_whitespace())
    {
        bail!("Firefox extension ID is invalid");
    }

    Ok(format!("{FIREFOX_EXTENSION_PREFIX}{extension_id}"))
}

pub fn inbox_dir() -> Result<PathBuf> {
    if let Some(configured_dir) = configured_inbox_dir()? {
        return Ok(configured_dir);
    }

    default_inbox_dir()
}

fn configured_inbox_dir() -> Result<Option<PathBuf>> {
    let Some(configured_dir) = env::var_os(INBOX_DIRECTORY_ENV) else {
        return Ok(None);
    };

    let configured_dir = PathBuf::from(configured_dir);
    if configured_dir.as_os_str().is_empty() || !configured_dir.is_absolute() {
        bail!("{INBOX_DIRECTORY_ENV} must be an absolute path");
    }

    Ok(Some(configured_dir))
}

#[cfg(target_os = "windows")]
fn default_inbox_dir() -> Result<PathBuf> {
    let local_app_data =
        env::var_os("LOCALAPPDATA").context("LOCALAPPDATA is required to locate the Barq inbox")?;
    Ok(PathBuf::from(local_app_data).join("Barq").join("inbox"))
}

#[cfg(not(target_os = "windows"))]
fn default_inbox_dir() -> Result<PathBuf> {
    if let Some(state_home) = env::var_os("XDG_STATE_HOME") {
        let state_home = PathBuf::from(state_home);
        if state_home.is_absolute() {
            return Ok(state_home.join("barq").join("inbox"));
        }
    }

    let home = env::var_os("HOME").context("HOME is required to locate the Barq inbox")?;
    Ok(PathBuf::from(home)
        .join(".local")
        .join("state")
        .join("barq")
        .join("inbox"))
}

pub fn init_stderr_logging() {
    let _ = tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .try_init();
}

#[cfg(test)]
mod tests {
    use super::{parse_allowed_origins, verify_caller_origin};

    #[test]
    fn configured_origins_normalize_and_deduplicate() {
        let allowed_origins = parse_allowed_origins(
            "chrome-extension://abcdefghijklmnopabcdefghijklmnop, firefox-extension://integration@barq.app ,chrome-extension://abcdefghijklmnopabcdefghijklmnop/",
        )
        .expect("configured origins should be accepted");

        assert_eq!(allowed_origins.len(), 2);
        assert!(allowed_origins.contains("chrome-extension://abcdefghijklmnopabcdefghijklmnop/"));
        assert!(allowed_origins.contains("firefox-extension://integration@barq.app"));
    }

    #[test]
    fn invalid_or_empty_origin_configuration_is_rejected() {
        assert!(parse_allowed_origins("").is_err());
        assert!(parse_allowed_origins("chrome-extension://*/").is_err());
        assert!(parse_allowed_origins("https://barq.app").is_err());
        assert!(parse_allowed_origins("moz-extension://dynamic-id/").is_err());
        assert!(parse_allowed_origins("chrome-extension://valid/, ").is_err());
    }

    #[test]
    fn caller_origin_must_match_the_configured_allowlist() {
        let allowed_origins = parse_allowed_origins("chrome-extension://allowed-extension/")
            .expect("allowed origin should parse");

        let permitted_args = vec![
            "barq-native-host".to_string(),
            "chrome-extension://allowed-extension/".to_string(),
        ];
        let rejected_args = vec![
            "barq-native-host".to_string(),
            "chrome-extension://other-extension/".to_string(),
        ];
        let missing_origin_args = vec!["barq-native-host".to_string()];
        let non_canonical_args = vec![
            "barq-native-host".to_string(),
            "chrome-extension://allowed-extension".to_string(),
        ];

        assert!(verify_caller_origin(&permitted_args, &allowed_origins).is_ok());
        assert!(verify_caller_origin(&rejected_args, &allowed_origins).is_err());
        assert!(verify_caller_origin(&missing_origin_args, &allowed_origins).is_err());
        assert!(verify_caller_origin(&non_canonical_args, &allowed_origins).is_err());
    }

    #[test]
    fn firefox_addon_id_must_match_the_configured_allowlist() {
        let allowed_origins = parse_allowed_origins("firefox-extension://integration@barq.app")
            .expect("Firefox add-on ID should parse");
        let permitted_args = vec![
            "barq-native-host".to_string(),
            "/opt/barq/app.barq.browser.json".to_string(),
            "integration@barq.app".to_string(),
        ];
        let rejected_args = vec![
            "barq-native-host".to_string(),
            "/opt/barq/app.barq.browser.json".to_string(),
            "other@barq.app".to_string(),
        ];

        assert!(verify_caller_origin(&permitted_args, &allowed_origins).is_ok());
        assert!(verify_caller_origin(&rejected_args, &allowed_origins).is_err());
    }
}
