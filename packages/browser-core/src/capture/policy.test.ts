import { describe, expect, it } from 'vitest';
import { isEligibleForAutoCapture } from './policy';

describe('isEligibleForAutoCapture', () => {
  it('allows a large direct download', () => {
    expect(isEligibleForAutoCapture({
      id: 4,
      url: 'https://downloads.example.test/archive.zip',
      fileSize: 20_000_000,
    })).toBe(true);
  });

  it.each([
    ['HLS manifest', { id: 1, url: 'https://media.example.test/video.m3u8', fileSize: 20_000_000 }],
    ['DASH manifest', { id: 2, url: 'https://media.example.test/video.mpd', fileSize: 20_000_000 }],
    ['redirected streaming manifest', {
      id: 5,
      url: 'https://media.example.test/watch',
      finalUrl: 'https://cdn.example.test/video.m3u8?token=opaque',
      fileSize: 20_000_000,
    }],
    ['known small file', { id: 3, url: 'https://downloads.example.test/readme.txt', fileSize: 512 }],
    ['incognito download', {
      id: 6,
      url: 'https://downloads.example.test/private.zip',
      fileSize: 20_000_000,
      incognito: true,
    }],
    ['non-HTTP URL', { id: 7, url: 'file:///tmp/archive.zip', fileSize: 20_000_000 }],
    ['streaming MIME type', {
      id: 8,
      url: 'https://media.example.test/video',
      mime: 'application/vnd.apple.mpegurl; charset=utf-8',
      fileSize: 20_000_000,
    }],
    ['streaming filename', {
      id: 9,
      url: 'https://media.example.test/video',
      filename: 'video.m3u8',
      fileSize: 20_000_000,
    }],
  ])('keeps %s in the browser', (_scenario, download) => {
    expect(isEligibleForAutoCapture(download)).toBe(false);
  });

  it('uses totalBytes when fileSize is unavailable and keeps known small files in the browser', () => {
    expect(isEligibleForAutoCapture({
      id: 10,
      url: 'https://downloads.example.test/small.zip',
      fileSize: -1,
      totalBytes: 1_024,
    })).toBe(false);
  });

  it('allows an exactly one MiB direct download', () => {
    expect(isEligibleForAutoCapture({
      id: 11,
      url: 'https://downloads.example.test/one-megabyte.zip',
      totalBytes: 1024 * 1024,
    })).toBe(true);
  });
});
