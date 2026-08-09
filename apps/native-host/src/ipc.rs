use anyhow::Result;

pub fn notify_desktop_app() -> Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::net::UnixStream;
        let path = std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| "/tmp".to_string())
            + "/barq/browser-v1.sock";
        if let Ok(mut stream) = UnixStream::connect(path) {
            use std::io::Write;
            let _ = stream.write_all(b"PING");
        }
    }
    #[cfg(windows)]
    {
        use std::fs::OpenOptions;
        use std::io::Write;
        if let Ok(mut file) = OpenOptions::new()
            .write(true)
            .open(r"\\.\pipe\barq-browser-v1")
        {
            let _ = file.write_all(b"PING");
        }
    }
    Ok(())
}
