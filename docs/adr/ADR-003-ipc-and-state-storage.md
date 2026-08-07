# ADR-003: Typed IPC Protocol & SQLite WAL State Persistence

- **Status**: Approved
- **Date**: 2026-08-07
- **Authors**: Barq Core Team
- **Context**: The decoupled engine daemon needs a fast, secure local communication interface with clients (GUI, CLI, Browser Native Host) and an atomic, crash-resilient storage system for active download tasks and range maps.

## Decision
1. **IPC Protocol**:
   - Use OS-local transport: Unix Domain Sockets on Linux/macOS and Named Pipes on Windows.
   - Use binary structured messages serialized via Protocol Buffers (Protobuf) or JSON-RPC 2.0.
   - Restrict IPC endpoints to local machine credentials to avoid firewall prompts.

2. **State Storage**:
   - Use SQLite in Write-Ahead Logging (WAL) mode.
   - Store download tasks, sources, compressed range maps, and event logs.
   - Write state updates every 250-500ms or after 4-16MiB progress to minimize write amplification.

## Consequences
### Positive
- Zero network exposure / no open TCP ports requiring firewall approval.
- High-speed IPC throughput for real-time progress updates.
- Atomic ACID guarantees preventing download state corruption during power loss or system crash.

### Negative / Trade-offs
- Named Pipes vs. Unix Sockets requires OS-specific IPC listener code.
- SQLite migration logic must be maintained forward for database schema updates.
