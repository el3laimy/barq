//! SQLite WAL persistent state store for Barq tasks and range maps.

use sqlite::Connection;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum StateStoreError {
    #[error("Database error: {0}")]
    Sqlite(#[from] sqlite::Error),
}

pub struct StateStore {
    connection: Connection,
}

impl StateStore {
    pub fn open_in_memory() -> Result<Self, StateStoreError> {
        let connection = sqlite::open(":memory:")?;
        let store = Self { connection };
        store.init_schema()?;
        Ok(store)
    }

    fn init_schema(&self) -> Result<(), StateStoreError> {
        let query = "
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                destination TEXT NOT NULL,
                file_size INTEGER DEFAULT 0,
                downloaded_bytes INTEGER DEFAULT 0,
                state TEXT NOT NULL
            );
        ";
        self.connection.execute(query)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_in_memory_store() {
        let store = StateStore::open_in_memory();
        assert!(store.is_ok());
    }
}
