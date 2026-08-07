# ADR-001: Decouple Download Engine from PyQt6 UI

- **Status**: Approved
- **Date**: 2026-08-07
- **Authors**: Barq Core Team
- **Context**: Barq Download Manager (v1.0) previously ran the download engine inside the Python PyQt6 application process. When the GUI crashed, closed, or froze, ongoing downloads were interrupted or terminated. Additionally, browser extensions and CLI tools could not interface with the download engine independently.

## Decision
We will decouple the Barq Download Engine into a standalone background process (`barq-engine` daemon). The PyQt6 desktop client will act solely as a thin GUI front-end communicating with the daemon over local inter-process communication (IPC).

## Consequences
### Positive
- **Fault Tolerance**: GUI crashes or window closes do not abort active downloads.
- **Multi-Interface**: CLI, PyQt6 GUI, and browser extensions interact with the same engine daemon seamlessly.
- **Resource Efficiency**: The headless engine daemon can run with minimal CPU and memory overhead.

### Negative / Trade-offs
- Requires IPC serialization overhead and handshake protocols.
- Requires maintaining state sync between daemon and client.
