/**
 * Barq Browser Protocol v1 — Zod Schemas and TypeScript Types
 *
 * This is the canonical definition of all messages exchanged between
 * barq-extension and barq-native-host. The Rust host uses mirrored
 * serde types generated from the same JSON Schema.
 *
 * @module @barq/protocol
 */

import { z } from 'zod';

// ─── DownloadEnvelope ────────────────────────────────────────────────

export const MediaCandidateSchema = z.object({
  url: z.string().url(),
  kind: z.enum(['hls', 'dash', 'media-file', 'page']),
});

export const MediaInfoSchema = z.object({
  pageTitle: z.string().max(512).optional(),
  candidates: z.array(MediaCandidateSchema).max(50).optional(),
  drmDetected: z.boolean().default(false),
});

export const BrowserInfoSchema = z.object({
  family: z.enum(['chrome', 'edge', 'firefox', 'chromium', 'brave', 'opera', 'vivaldi']),
  version: z.string(),
  profileMode: z.enum(['normal', 'incognito', 'container']),
  cookieStoreId: z.string().optional(),
  tabId: z.number().int().optional(),
  frameId: z.number().int().optional(),
});

export const FileInfoSchema = z.object({
  suggestedName: z.string().max(255).optional(),
  mimeType: z.string().max(255).optional(),
  size: z.number().int().nonnegative().optional(),
});

export const RequestInfoSchema = z.object({
  url: z.string().url(),
  finalUrl: z.string().url().optional(),
  method: z.enum(['GET', 'HEAD', 'POST']).default('GET'),
  referrer: z.string().url().optional(),
  pageUrl: z.string().url().optional(),
  initiator: z.string().optional(),
  headers: z.record(z.string()).default({}),
  cookieHeader: z.string().max(64_000).optional(),
  body: z.string().max(64_000).optional(),
});

export const DownloadEnvelopeSchema = z.object({
  protocol: z.literal('barq.browser.v1'),
  requestId: z.string().uuid(),
  idempotencyKey: z.string().min(32).max(128),
  createdAt: z.string().datetime(),
  source: z.enum(['auto-download', 'context-menu', 'toolbar', 'media', 'blob-relay']),
  request: RequestInfoSchema,
  file: FileInfoSchema,
  browser: BrowserInfoSchema,
  media: MediaInfoSchema.optional(),
});

export type DownloadEnvelope = z.infer<typeof DownloadEnvelopeSchema>;
export type MediaCandidate = z.infer<typeof MediaCandidateSchema>;
export type MediaInfo = z.infer<typeof MediaInfoSchema>;
export type BrowserInfo = z.infer<typeof BrowserInfoSchema>;
export type FileInfo = z.infer<typeof FileInfoSchema>;
export type RequestInfo = z.infer<typeof RequestInfoSchema>;

// ─── Host Requests (Extension → Host) ───────────────────────────────

export const HelloRequestSchema = z.object({
  type: z.literal('hello'),
  protocols: z.array(z.string()),
  extensionVersion: z.string(),
  browser: z.object({
    family: z.string(),
    version: z.string(),
  }),
  capabilities: z.array(z.string()),
});

export const PrepareCaptureRequestSchema = z.object({
  type: z.literal('prepare_capture'),
  correlationId: z.string().uuid(),
  envelope: DownloadEnvelopeSchema,
});

export const HostRequestSchema = z.discriminatedUnion('type', [
  HelloRequestSchema,
  PrepareCaptureRequestSchema,
]);

export type HelloRequest = z.infer<typeof HelloRequestSchema>;
export type PrepareCaptureRequest = z.infer<typeof PrepareCaptureRequestSchema>;
export type HostRequest = z.infer<typeof HostRequestSchema>;

// ─── Host Responses (Host → Extension) ──────────────────────────────

export const HelloAckSchema = z.object({
  type: z.literal('hello_ack'),
  protocol: z.literal('barq.browser.v1'),
  hostVersion: z.string(),
  appVersion: z.string().optional(),
  healthy: z.boolean(),
  capabilities: z.array(z.string()),
  limits: z.object({
    maxMessageBytes: z.number().int().positive(),
    maxCookieBytes: z.number().int().positive(),
  }),
});

export const AcceptedResponseSchema = z.object({
  status: z.literal('accepted'),
  correlationId: z.string(),
  transferId: z.string().uuid(),
  durable: z.literal(true),
});

export const RejectedResponseSchema = z.object({
  status: z.literal('rejected'),
  correlationId: z.string(),
  code: z.enum([
    'INVALID_REQUEST',
    'APP_PROTOCOL_TOO_OLD',
    'UNSUPPORTED_METHOD',
    'DRM_PROTECTED',
    'QUEUE_UNAVAILABLE',
  ]),
  retryable: z.boolean(),
});

export const HostResponseSchema = z.discriminatedUnion('status', [
  AcceptedResponseSchema,
  RejectedResponseSchema,
]);

export type HelloAck = z.infer<typeof HelloAckSchema>;
export type AcceptedResponse = z.infer<typeof AcceptedResponseSchema>;
export type RejectedResponse = z.infer<typeof RejectedResponseSchema>;
export type HostResponse = z.infer<typeof HostResponseSchema>;

// ─── Blob Relay Messages ─────────────────────────────────────────────

export const BlobRelayMessageSchema = z.discriminatedUnion('type', [
  z.object({
    type: z.literal('blob_begin'),
    transferId: z.string(),
    name: z.string().optional(),
    size: z.number().optional(),
    mime: z.string().optional(),
  }),
  z.object({
    type: z.literal('blob_chunk'),
    transferId: z.string(),
    sequence: z.number().int().nonnegative(),
    dataBase64: z.string(),
    sha256: z.string(),
  }),
  z.object({
    type: z.literal('blob_end'),
    transferId: z.string(),
    chunks: z.number().int().nonnegative(),
    sha256: z.string(),
  }),
  z.object({
    type: z.literal('blob_abort'),
    transferId: z.string(),
    reason: z.string(),
  }),
]);

export type BlobRelayMessage = z.infer<typeof BlobRelayMessageSchema>;

// ─── Error Codes ─────────────────────────────────────────────────────

export const ErrorCodes = {
  HOST_NOT_REGISTERED: 'HOST_NOT_REGISTERED',
  EXTENSION_ID_NOT_ALLOWED: 'EXTENSION_ID_NOT_ALLOWED',
  SITE_PERMISSION_REQUIRED: 'SITE_PERMISSION_REQUIRED',
  APP_PROTOCOL_TOO_OLD: 'APP_PROTOCOL_TOO_OLD',
  CAPTURE_TIMEOUT: 'CAPTURE_TIMEOUT',
  DRM_PROTECTED: 'DRM_PROTECTED',
} as const;

export type ErrorCode = (typeof ErrorCodes)[keyof typeof ErrorCodes];

// ─── Utilities ───────────────────────────────────────────────────────

/** Secret headers that must never appear in logs or diagnostics. */
export const SECRET_HEADERS = new Set(['cookie', 'authorization', 'proxy-authorization']);

/** Sanitize a filename to prevent path traversal and OS-reserved names. */
export function sanitizeFilename(input: string, fallback = 'download'): string {
  const leaf = input.replace(/\\/g, '/').split('/').pop() ?? fallback;
  const cleaned = leaf
    .normalize('NFKC')
    .replace(/[\x00-\x1f]/g, '')
    .replace(/[<>:"/\\|?*]/g, '_')
    .replace(/[. ]+$/g, '')
    .slice(0, 180);
  const reserved = /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i;
  return !cleaned || reserved.test(cleaned) ? `_${cleaned || fallback}` : cleaned;
}

/** Redact sensitive fields from an envelope for diagnostics export. */
export function redactEnvelope(envelope: DownloadEnvelope): DownloadEnvelope {
  const copy = structuredClone(envelope);
  copy.request.cookieHeader = copy.request.cookieHeader ? '<redacted>' : undefined;
  for (const key of Object.keys(copy.request.headers)) {
    if (SECRET_HEADERS.has(key.toLowerCase())) {
      copy.request.headers[key] = '<redacted>';
    }
  }
  copy.request.url = redactSignedQuery(copy.request.url);
  if (copy.request.finalUrl) {
    copy.request.finalUrl = redactSignedQuery(copy.request.finalUrl);
  }
  return copy;
}

/** Replace known sensitive query parameters with [REDACTED]. */
function redactSignedQuery(url: string): string {
  try {
    const u = new URL(url);
    const sensitive = ['token', 'key', 'access_token', 'auth', 'password', 'secret', 'sig', 'signature'];
    for (const param of sensitive) {
      if (u.searchParams.has(param)) {
        u.searchParams.set(param, '[REDACTED]');
      }
    }
    return u.toString();
  } catch {
    return url;
  }
}
