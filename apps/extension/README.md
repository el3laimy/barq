# Barq Browser Extension

Browser extension for Barq Download Manager. Intercepts eligible downloads and hands them off to the Barq desktop application via Native Messaging.

## Architecture

```
apps/extension/          WXT browser extension (Manifest V3)
packages/browser-core/   Capture coordination, context assembly, Native Client
packages/protocol-ts/    Zod schemas for barq.browser.v1 protocol
packages/browser-adapters/ Browser-specific adapter layer
apps/native-host/        Rust Native Messaging host binary
```

## Requirements

- **Node.js** ≥ 20
- **pnpm** ≥ 10
- **Rust** (only for Native Host)

## Build

```bash
# Install all workspace dependencies
pnpm install

# Build Chrome MV3 extension
pnpm --filter @barq/extension build

# Build Firefox extension
pnpm --filter @barq/extension build:firefox

# Development mode (auto-reload)
pnpm --filter @barq/extension dev:chrome
pnpm --filter @barq/extension dev:firefox

# Type-check
pnpm --filter @barq/extension typecheck

# Run tests
pnpm --filter @barq/extension test
```

## Chrome / Edge Developer Mode Installation

1. Build the extension:
   ```bash
   pnpm --filter @barq/extension build
   ```

2. Open your browser's extension page:
   - **Chrome**: `chrome://extensions`
   - **Edge**: `edge://extensions`

3. Enable **Developer mode** (toggle in top-right).

4. Click **"Load unpacked"**.

5. Select the generated output directory:
   ```
   apps/extension/.output/chrome-mv3/
   ```

> ⚠️ Do **NOT** load the `apps/extension/` source directory directly.
> WXT generates the final manifest and bundled assets into `.output/chrome-mv3/`.

## Firefox Developer Mode Installation

1. Build the Firefox extension:
   ```bash
   pnpm --filter @barq/extension build:firefox
   ```

2. Open `about:debugging#/runtime/this-firefox`

3. Click **"Load Temporary Add-on"**

4. Select `manifest.json` inside:
   ```
   apps/extension/.output/firefox-mv3/
   ```

## Validate Build

Run the automated build validator:

```bash
node scripts/validate-extension-build.mjs
```

Run the full diagnostics:

```bash
python scripts/doctor_browser_integration.py
```

## Troubleshooting

### Extension won't load / manifest errors

This is a **build issue**. The output directory doesn't have a valid `manifest.json` or is missing referenced files.

**Fix**: Rebuild with `pnpm --filter @barq/extension build` and load from `.output/chrome-mv3/`.

### Extension loads but "Barq not detected"

This is a **Native Messaging issue**, separate from the extension itself. The extension installed correctly, but the Barq desktop application's Native Messaging host is not registered.

**Fix**: Ensure the Barq desktop application is installed and has registered its Native Messaging manifest (`app.barq.browser.json`).

### Popup is blank

Check the service worker console in `chrome://extensions` → Barq → "Inspect views: service worker". Look for module loading errors.

### Context menu doesn't appear

The context menu registers on `runtime.onInstalled`. Try disabling and re-enabling the extension, or click "Update" on the extension card.

## Native Messaging Host

The extension communicates with the Barq desktop application through Chrome's Native Messaging API using host name: `app.barq.browser`.

The Native Host is a Rust binary in `apps/native-host/`. It must be:
1. Compiled (`cargo build --manifest-path apps/native-host/Cargo.toml`)
2. Registered with a Native Messaging manifest in the browser's expected location
3. The manifest's `allowed_origins` must include the extension's ID

### Native Host Name Consistency

| Component | Value |
|---|---|
| Extension (client.ts) | `app.barq.browser` |
| Native Host manifest | `app.barq.browser` |
| Manifest file name | `app.barq.browser.json` |

## Permissions

| Permission | Required | Reason |
|---|---|---|
| `nativeMessaging` | Yes | Communication with Barq desktop app |
| `contextMenus` | Yes | "Download with Barq" right-click menu |
| `storage` | Yes | Persist auto-capture preferences |
| `alarms` | Yes | Recovery timer for pending captures |
| `activeTab` | Yes | Read current tab URL for context |
| `downloads` | Yes | Intercept browser downloads |
| `cookies` | Optional | Authenticated download support (per-site) |
| `http/https hosts` | Optional | Cookie access scope |
