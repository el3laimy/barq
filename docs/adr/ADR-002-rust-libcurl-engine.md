# ADR-002: Rust Workspace & libcurl Multi for High-Throughput Download Core

- **Status**: Approved
- **Date**: 2026-08-07
- **Authors**: Barq Core Team
- **Context**: High-speed parallel download acceleration requires memory safety, low CPU overhead, zero garbage collection pauses, and robust battle-tested HTTP/1.1, HTTP/2, and HTTP/3 networking capability. Pure Python asyncio lacks optimal low-level network socket multiplexing under extreme multi-gigabit throughput.

## Decision
We will build the next-generation `barq-engine` daemon in Rust using a modular Cargo Workspace architecture and leverage `libcurl Multi` (`curl-rust` / `libcurl`) as the core network transport layer.

## Key Technical Components
1. **`engine-core`**: High-level task coordination and state management.
2. **`transport-curl`**: `libcurl Multi` handle pooling and async multi-stream I/O.
3. **`adaptive-scheduler`**: Dynamic Range Queue and Work Stealing algorithm (AIMD).
4. **`file-writer`**: High-performance persistent disk writer with preallocation and sparse file support.
5. **`state-store`**: SQLite WAL persistence for atomic checkpoint recovery.

## Consequences
### Positive
- Maximum single-thread and multi-thread I/O throughput with minimal memory footprint.
- Native HTTP/2 & HTTP/3 multiplexing and connection reuse via libcurl.
- Strong memory safety guarantees without runtime GC overhead.

### Negative / Trade-offs
- Requires Rust toolchain compilation during build pipelines.
- FFI bindings for C/libcurl integration require clean error wrappers.
