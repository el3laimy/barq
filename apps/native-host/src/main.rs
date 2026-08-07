mod framing;
mod protocol;
mod inbox;
mod ipc;
mod platform;

use crate::framing::{read_native_message, write_native_message};
use crate::protocol::{HostRequest, HostResponse, HostService};
use crate::platform::{init_stderr_logging, verify_caller_origin, release_allowed_origins, load_runtime_config, redact_error};

fn main() -> anyhow::Result<()> {
    init_stderr_logging();
    let args: Vec<String> = std::env::args().collect();
    verify_caller_origin(&args, &release_allowed_origins())?;
    
    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut input = stdin.lock();
    let mut output = stdout.lock();
    
    let service = HostService::new(load_runtime_config()?)?;
    
    while let Some(payload) = read_native_message(&mut input)? {
        let response = match serde_json::from_slice::<HostRequest>(&payload) {
            Ok(request) => service.handle(request),
            Err(error) => HostResponse::invalid_request(redact_error(error)),
        };
        write_native_message(&mut output, &response)?;
        let _ = ipc::notify_desktop_app();
    }
    
    Ok(())
}
