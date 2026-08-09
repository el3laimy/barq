use anyhow::{anyhow, Context, Result};
use serde::Serialize;
use std::io::{Read, Write};

const MAX_INBOUND: usize = 8 * 1024 * 1024;
const MAX_OUTBOUND: usize = 900 * 1024;

pub fn read_native_message<R: Read>(mut reader: R) -> Result<Option<Vec<u8>>> {
    let mut length_bytes = [0_u8; 4];
    match reader.read(&mut length_bytes[..1])? {
        0 => return Ok(None),
        _ => reader.read_exact(&mut length_bytes[1..])?,
    }

    let length = u32::from_le_bytes(length_bytes) as usize;
    if length > MAX_INBOUND {
        return Err(anyhow!("Native message exceeds the inbound limit"));
    }

    let mut payload = vec![0; length];
    reader.read_exact(&mut payload)?;
    Ok(Some(payload))
}

pub fn write_native_message<W: Write, T: Serialize>(mut writer: W, message: &T) -> Result<()> {
    let payload = serde_json::to_vec(message)?;
    if payload.len() > MAX_OUTBOUND {
        return Err(anyhow!("Native response exceeds the outbound limit"));
    }

    let length =
        u32::try_from(payload.len()).context("Native response length cannot be encoded")?;
    writer.write_all(&length.to_le_bytes())?;
    writer.write_all(&payload)?;
    writer.flush()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{read_native_message, write_native_message, MAX_OUTBOUND};
    use std::io::Cursor;

    #[test]
    fn little_endian_frame_is_decoded() {
        let wire = [3_u8, 0, 0, 0, b'a', b'b', b'c'];

        let payload = read_native_message(Cursor::new(wire))
            .expect("frame should decode")
            .expect("frame should contain a payload");

        assert_eq!(payload, b"abc");
    }

    #[test]
    fn truncated_frame_is_rejected_instead_of_treated_as_eof() {
        let truncated_header = [1_u8, 0];
        let truncated_payload = [3_u8, 0, 0, 0, b'a'];

        assert!(read_native_message(Cursor::new(truncated_header)).is_err());
        assert!(read_native_message(Cursor::new(truncated_payload)).is_err());
    }

    #[test]
    fn oversized_frame_is_rejected_before_allocation() {
        let oversized_header = u32::MAX.to_le_bytes();

        assert!(read_native_message(Cursor::new(oversized_header)).is_err());
    }

    #[test]
    fn outbound_frame_uses_little_endian_length_prefix() {
        let mut wire = Vec::new();

        write_native_message(&mut wire, &"ok").expect("response should encode");

        assert_eq!(&wire[..4], &[4, 0, 0, 0]);
        assert_eq!(&wire[4..], br#""ok""#);
    }

    #[test]
    fn oversized_response_is_rejected() {
        let response = "a".repeat(MAX_OUTBOUND + 1);

        assert!(write_native_message(Vec::new(), &response).is_err());
    }
}
