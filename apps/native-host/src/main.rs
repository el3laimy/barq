mod framing;
mod inbox;
mod ipc;
mod platform;
mod protocol;

use crate::framing::{read_native_message, write_native_message};
use crate::platform::{init_stderr_logging, load_runtime_config, verify_caller_origin};
use crate::protocol::{HostRequest, HostResponse, HostService};

fn main() -> anyhow::Result<()> {
    init_stderr_logging();
    let args: Vec<String> = std::env::args().collect();
    let runtime_config = load_runtime_config()?;
    verify_caller_origin(&args, runtime_config.allowed_origins())?;

    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut input = stdin.lock();
    let mut output = stdout.lock();

    let service = HostService::new(runtime_config.inbox_dir().to_path_buf())?;

    while let Some(payload) = read_native_message(&mut input)? {
        let response = match serde_json::from_slice::<HostRequest>(&payload) {
            Ok(request) => service.handle(request),
            Err(_) => HostResponse::invalid_request(),
        };
        let should_notify_desktop = response.is_accepted();
        write_native_message(&mut output, &response)?;
        if should_notify_desktop {
            let _ = ipc::notify_desktop_app();
        }
    }

    Ok(())
}
