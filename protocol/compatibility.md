# Barq Browser Protocol — Compatibility & ADR Log

## Protocol Identity

- **Name**: `barq.browser.v1`
- **Schema**: [`barq-browser-v1.schema.json`](./barq-browser-v1.schema.json)
- **Transport**: Chrome/Edge/Firefox Native Messaging (stdin/stdout, 32-bit LE length-prefixed JSON)
- **Response Size Limit**: < 1 MiB (browser hard limit); Barq policy: 900 KB

## Versioning Rules

1. Protocol version is a **stable name** (e.g., `barq.browser.v1`), not SemVer.
2. Extension version, Host version, and App version use SemVer independently.
3. New **optional** fields may be added within `v1` without breaking compatibility.
4. Changing the **meaning** of an existing field requires a new protocol version (`v2`).
5. Host may support `v1` and `v2` simultaneously during a transition period.
6. `hello` handshake negotiates the active protocol and capabilities.

## Capability Negotiation

| Capability | Meaning |
| :--- | :--- |
| `auto-capture` | Extension supports Pause/ACK/Cancel auto-interception |
| `partitioned-cookies` | Extension can provide `partitionKey` in cookie queries |
| `blob-relay-v1` | Extension supports chunked blob transfer |
| `durable-inbox` | Host persists envelopes to filesystem before ACK |
| `media-page-handoff` | Host accepts page URL + media candidates |

---

## Architecture Decision Records (ADR)

### ADR-001: WXT + TypeScript instead of raw JS files

**Decision**: Use WXT framework with TypeScript for the browser extension.

**Rationale**: Reduces cross-browser divergence (Chrome/Edge/Firefox) with a single codebase. Generates proper manifests per target. TypeScript provides compile-time safety for the complex protocol types. Core business logic remains framework-agnostic in `packages/browser-core/`.

**Alternatives rejected**:
- Raw WebExtensions: Manual manifest duplication and browser-specific build scripts
- Plasmo: Larger framework dependency with less build flexibility

---

### ADR-002: Rust Native Host instead of Python bridge

**Decision**: Replace `bridge.py` with a compiled Rust binary (`barq-native-host`).

**Rationale**:
- Eliminates Python runtime dependency on end-user machines
- Prevents `stdout` corruption from Python print/logging statements
- Memory-safe message framing with explicit size limits
- Future alignment with the Rust download engine (`engine/`)
- Smaller binary, faster startup, no antivirus false positives from script interpreters

**Migration**: Python `bridge.py` is archived. A transitional `BrowserInboxWatcher` (Python/PyQt) consumes the Durable Inbox from the desktop app side.

---

### ADR-003: Pause/ACK/Cancel (not Cancel-then-Send)

**Decision**: The extension pauses the browser download first, waits for a Durable ACK from the host, then cancels. On any failure, it resumes the browser download.

**Rationale**: The current code cancels the download immediately and then attempts to send the URL. If the host is unavailable, the download is permanently lost. The new protocol guarantees zero download loss.

---

### ADR-004: Durable Inbox before ACK

**Decision**: The host writes the DownloadEnvelope to a filesystem inbox (tmp → fsync → atomic rename) before sending `accepted` back to the extension.

**Rationale**: Even if Barq desktop app is not running, the envelope survives on disk. The app picks it up on next startup. This decouples the host from the app's availability.

---

### ADR-005: Named Pipe / Unix Socket instead of localhost TCP

**Decision**: Replace the `127.0.0.1:19375` TCP socket with:
- **Linux/macOS**: Unix Domain Socket at `$XDG_RUNTIME_DIR/barq/browser-v1.sock` (0600)
- **Windows**: Named Pipe at `\\.\pipe\barq-browser-v1` with user-only ACL

**Rationale**: TCP on localhost accepts connections from any local process without identity verification. Unix sockets and named pipes support filesystem permissions and peer credential checking, reducing the attack surface.

---

### ADR-006: Progressive Permission Ladder

**Decision**: Request only minimal permissions at install time (`nativeMessaging`, `contextMenus`, `storage`, `activeTab`, `downloads`). Sensitive permissions (`cookies`, `webRequest`, `<all_urls>`) are requested incrementally when the user enables a feature.

**Rationale**: Requesting `<all_urls>` upfront triggers user distrust and store review scrutiny. Progressive permissions explain each access need in context.

---

### ADR-007: Request Ledger (short-lived)

**Decision**: Maintain a short-lived in-memory ledger of `webRequest` events to correlate `downloads.onCreated` items with their original request headers, cookies, and redirect chains.

**Rationale**: The Downloads API does not provide a `requestId` linkable to `webRequest` events. Probabilistic matching by URL, time window, and tab is necessary. The ledger expires entries after ~30 seconds to avoid persistent browsing history.

---

### ADR-008: Media page handoff + candidates

**Decision**: The extension sends the page URL, title, and detected media manifest URLs to Barq. Barq decides whether to use yt-dlp, direct manifest download, or other strategies.

**Rationale**: Website-specific parsing changes faster than store review cycles. Keeping site-specific logic in the desktop app (updateable independently) prevents extension rejection and breakage.

---

### ADR-009: Explicit blob relay only

**Decision**: Blob relay (reading `blob:` URLs via content script and streaming chunks to the host) is only triggered by explicit user action, never automatically.

**Rationale**: Automatic blob interception is expensive (CPU/memory), may break web applications, and is unnecessary for most downloads. The feature covers generated files (PDFs, exports) with user intent.

---

### ADR-010: Store-specific feature flags

**Decision**: Features that conflict with a specific store's policies are disabled at build time for that store's package, rather than attempting to circumvent review.

**Rationale**: Compliance over cleverness. Each store build passes `wxt build -b <target>` with appropriate feature flags. The desktop app retains full functionality regardless.
