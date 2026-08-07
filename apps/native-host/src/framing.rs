use anyhow::{anyhow, Result};
use std::io::{Read, Write};
use serde::Serialize;

const MAX_INBOUND: usize = 8 * 1024 * 1024; // 8MB
const MAX_OUTBOUND: usize = 900 * 1024;     // 900KB

pub fn read_native_message<R: Read>(mut reader: R) -> Result<Option<Vec<u8>>> {
    let mut len_buf = [0u8; 4];
    match reader.read_exact(&mut len_buf) {
        Ok(_) => (),
        Err(e) if e.kind() == std::io::ErrorKind::UnexpectedEof => return Ok(None),
        Err(e) => return Err(e.into()),
    }

    let len = u32::from_ne_bytes(len_buf) as usize;

    if len > MAX_INBOUND {
        return Err(anyhow!("Message too large: {}", len));
    }

    if len == 0 {
        return Ok(Some(vec![]));
    }

    let mut buffer = vec![0; len];
    reader.read_exact(&mut buffer)?;
    Ok(Some(buffer))
}

pub fn write_native_message<W: Write, T: Serialize>(mut writer: W, message: &T) -> Result<()> {
    let payload = serde_json::to_vec(message)?;
    let len = payload.len();

    if len > MAX_OUTBOUND {
        return Err(anyhow!("Response too large: {}", len));
    }

    let len_bytes = (len as u32).to_ne_bytes();
    writer.write_all(&len_bytes)?;
    writer.write_all(&payload)?;
    writer.flush()?;
    Ok(())
}
