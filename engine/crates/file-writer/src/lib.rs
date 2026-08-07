//! High-performance persistent file writer with preallocation and chunk writing at offsets.

use std::fs::OpenOptions;
use std::io::{Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Error, Debug)]
pub enum WriterError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
}

pub struct FileWriter {
    file_path: PathBuf,
}

impl FileWriter {
    pub fn new(path: impl AsRef<Path>) -> Self {
        Self {
            file_path: path.as_ref().to_path_buf(),
        }
    }

    pub fn preallocate(&self, total_bytes: u64) -> Result<(), WriterError> {
        let file = OpenOptions::new()
            .write(true)
            .create(true)
            .open(&self.file_path)?;
            
        if total_bytes > 0 {
            file.set_len(total_bytes)?;
        }
        Ok(())
    }

    pub fn write_at(&self, offset: u64, data: &[u8]) -> Result<(), WriterError> {
        let mut file = OpenOptions::new()
            .write(true)
            .open(&self.file_path)?;
            
        file.seek(SeekFrom::Start(offset))?;
        file.write_all(data)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::NamedTempFile;

    #[test]
    fn test_preallocate_and_write() {
        let temp_file = NamedTempFile::new().unwrap();
        let writer = FileWriter::new(temp_file.path());
        assert!(writer.preallocate(1024).is_ok());
        assert!(writer.write_at(0, b"BarqEngineTest").is_ok());
    }
}
