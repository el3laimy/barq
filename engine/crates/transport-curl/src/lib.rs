//! libcurl Multi transport wrapper for multi-segment high-speed HTTP downloads.

use curl::easy::Easy;
use curl::multi::Multi;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum TransportError {
    #[error("Curl transport error: {0}")]
    Curl(#[from] curl::Error),
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
}

pub struct CurlTransport {
    multi: Multi,
}

impl CurlTransport {
    pub fn new() -> Result<Self, TransportError> {
        let multi = Multi::new();
        Ok(Self { multi })
    }

    pub fn create_easy_handle(url: &str) -> Result<Easy, TransportError> {
        let mut easy = Easy::new();
        easy.url(url)?;
        easy.follow_location(true)?;
        easy.useragent("BarqEngine/1.0")?;
        Ok(easy)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_transport_initialization() {
        let transport = CurlTransport::new();
        assert!(transport.is_ok());
    }
}
