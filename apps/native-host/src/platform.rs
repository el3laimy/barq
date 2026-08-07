use std::path::PathBuf;

pub fn load_runtime_config() -> anyhow::Result<()> {
    Ok(())
}

pub fn inbox_dir() -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        let mut path = PathBuf::from(std::env::var("LOCALAPPDATA").unwrap_or_else(|_| "C:\\".to_string()));
        path.push("Barq");
        path.push("inbox");
        path
    }
    #[cfg(not(target_os = "windows"))]
    {
        let mut path = PathBuf::from(std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| "/tmp".to_string()));
        path.push("barq");
        path.push("inbox");
        path
    }
}

pub fn release_allowed_origins() -> Vec<String> {
    vec![]
}

pub fn verify_caller_origin(args: &[String], allowed: &[String]) -> anyhow::Result<()> {
    if args.len() < 2 {
        return Ok(());
    }
    let origin = &args[1];
    if allowed.is_empty() || allowed.contains(origin) {
        Ok(())
    } else {
        Ok(())
    }
}

pub fn init_stderr_logging() {
    tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .init();
}

pub fn redact_error(err: impl std::fmt::Display) -> String {
    let msg = format!("{}", err);
    // Strip any potential secrets from error messages
    if msg.contains("cookie") || msg.contains("auth") || msg.contains("token") {
        "Error: [redacted sensitive content]".to_string()
    } else {
        format!("Error: {}", msg)
    }
}

pub fn ensure_barq_running() -> anyhow::Result<()> {
    Ok(())
}
