/**
 * @barq/protocol — Unit tests for Zod schemas and utilities
 */

import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'fs';
import { join } from 'path';
import {
  DownloadEnvelopeSchema,
  HelloRequestSchema,
  HelloAckSchema,
  AcceptedResponseSchema,
  RejectedResponseSchema,
  HostResponseSchema,
  sanitizeFilename,
  redactEnvelope,
} from './index';

const FIXTURES_DIR = join(__dirname, '..', '..', 'test-fixtures');

function loadFixture(sub: string, name: string): unknown {
  const path = join(FIXTURES_DIR, sub, name);
  return JSON.parse(readFileSync(path, 'utf-8'));
}

// ─── DownloadEnvelope Schema Validation ──────────────────────────────

describe('DownloadEnvelopeSchema', () => {
  const validFiles = readdirSync(join(FIXTURES_DIR, 'valid')).filter(f => f.endsWith('.json'));

  for (const file of validFiles) {
    it(`should accept valid fixture: ${file}`, () => {
      const data = loadFixture('valid', file);
      const result = DownloadEnvelopeSchema.safeParse(data);
      // DRM fixtures are valid envelopes (DRM rejection is host logic, not schema)
      expect(result.success).toBe(true);
    });
  }

  const invalidFiles = readdirSync(join(FIXTURES_DIR, 'invalid')).filter(f => f.endsWith('.json'));

  for (const file of invalidFiles) {
    it(`should reject invalid fixture: ${file}`, () => {
      const data = loadFixture('invalid', file);
      const result = DownloadEnvelopeSchema.safeParse(data);
      expect(result.success).toBe(false);
    });
  }
});

// ─── HelloRequest ────────────────────────────────────────────────────

describe('HelloRequestSchema', () => {
  it('should accept a valid hello request', () => {
    const result = HelloRequestSchema.safeParse({
      type: 'hello',
      protocols: ['barq.browser.v1'],
      extensionVersion: '1.0.0',
      browser: { family: 'chrome', version: '146.0' },
      capabilities: ['auto-capture', 'partitioned-cookies'],
    });
    expect(result.success).toBe(true);
  });

  it('should reject hello without protocols', () => {
    const result = HelloRequestSchema.safeParse({
      type: 'hello',
      extensionVersion: '1.0.0',
      browser: { family: 'chrome', version: '146.0' },
      capabilities: [],
    });
    expect(result.success).toBe(false);
  });
});

// ─── HelloAck ────────────────────────────────────────────────────────

describe('HelloAckSchema', () => {
  it('should accept a valid hello_ack', () => {
    const result = HelloAckSchema.safeParse({
      type: 'hello_ack',
      protocol: 'barq.browser.v1',
      hostVersion: '1.0.0',
      appVersion: '0.9.0',
      healthy: true,
      capabilities: ['durable-inbox', 'media-page-handoff'],
      limits: { maxMessageBytes: 900000, maxCookieBytes: 64000 },
    });
    expect(result.success).toBe(true);
  });
});

// ─── HostResponse ────────────────────────────────────────────────────

describe('HostResponseSchema', () => {
  it('should accept an accepted response', () => {
    const result = HostResponseSchema.safeParse({
      status: 'accepted',
      correlationId: 'test-123',
      transferId: 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
      durable: true,
    });
    expect(result.success).toBe(true);
  });

  it('should accept a rejected response', () => {
    const result = HostResponseSchema.safeParse({
      status: 'rejected',
      correlationId: 'test-456',
      code: 'DRM_PROTECTED',
      retryable: false,
    });
    expect(result.success).toBe(true);
  });

  it('should reject unknown rejection codes', () => {
    const result = RejectedResponseSchema.safeParse({
      status: 'rejected',
      correlationId: 'test-789',
      code: 'UNKNOWN_CODE',
      retryable: false,
    });
    expect(result.success).toBe(false);
  });
});

// ─── sanitizeFilename ────────────────────────────────────────────────

describe('sanitizeFilename', () => {
  it('should strip path separators', () => {
    expect(sanitizeFilename('../../etc/passwd')).toBe('passwd');
  });

  it('should replace Windows-reserved characters', () => {
    expect(sanitizeFilename('file<name>:test?.zip')).toBe('file_name__test_.zip');
  });

  it('should handle Windows reserved names', () => {
    expect(sanitizeFilename('CON')).toBe('_CON');
    expect(sanitizeFilename('NUL.txt')).toBe('_NUL.txt');
    expect(sanitizeFilename('COM1')).toBe('_COM1');
  });

  it('should truncate to 180 chars', () => {
    const long = 'a'.repeat(300) + '.zip';
    expect(sanitizeFilename(long).length).toBeLessThanOrEqual(180);
  });

  it('should use fallback for empty input', () => {
    expect(sanitizeFilename('')).toBe('_download');
  });

  it('should strip trailing dots and spaces', () => {
    expect(sanitizeFilename('file.txt...')).toBe('file.txt');
    expect(sanitizeFilename('file.txt   ')).toBe('file.txt');
  });

  it('should strip control characters', () => {
    expect(sanitizeFilename('file\x00name\x1f.txt')).toBe('filename.txt');
  });
});

// ─── redactEnvelope ──────────────────────────────────────────────────

describe('redactEnvelope', () => {
  it('should redact cookie header', () => {
    const fixture = loadFixture('valid', 'context-menu-with-cookies.json');
    const parsed = DownloadEnvelopeSchema.parse(fixture);
    const redacted = redactEnvelope(parsed);
    expect(redacted.request.cookieHeader).toBe('<redacted>');
    // Original unchanged
    expect(parsed.request.cookieHeader).toBe('session_id=abc123def456; csrf_token=xyz789');
  });

  it('should redact Authorization header', () => {
    const fixture = loadFixture('valid', 'auto-download-basic.json');
    const parsed = DownloadEnvelopeSchema.parse(fixture);
    // Add an Authorization header for testing
    parsed.request.headers['Authorization'] = 'Bearer secret-token';
    const redacted = redactEnvelope(parsed);
    expect(redacted.request.headers['Authorization']).toBe('<redacted>');
  });

  it('should not modify non-secret headers', () => {
    const fixture = loadFixture('valid', 'auto-download-basic.json');
    const parsed = DownloadEnvelopeSchema.parse(fixture);
    const redacted = redactEnvelope(parsed);
    expect(redacted.request.headers['Accept']).toBe('application/octet-stream');
  });
});
