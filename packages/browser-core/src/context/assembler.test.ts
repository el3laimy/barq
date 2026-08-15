import { describe, expect, it } from 'vitest';
import {
  allowedRequestHeaders,
  cookieQueryForNormalProfile,
  ContextAssembler,
} from './assembler';

describe('ContextAssembler', () => {
  it('passes scoped cookies and approved headers without forwarding Authorization', async () => {
    const assembler = new ContextAssembler(
      { family: 'firefox', version: '128.0' },
      {
        collect: async () => ({
          cookieHeader: 'session=browser-cookie',
          headers: {
            Accept: 'application/octet-stream',
            Authorization: 'Bearer should-not-leave-the-browser',
            'X-Trace': 'not-forwarded',
          },
        }),
      },
    );

    const envelope = await assembler.fromContextMenu(
      { linkUrl: 'https://downloads.example.test/private.zip', pageUrl: 'https://app.example.test' },
      { id: 9, url: 'https://app.example.test', cookieStoreId: 'firefox-default' },
    );

    expect(envelope?.request.cookieHeader).toBe('session=browser-cookie');
    expect(envelope?.request.headers).toEqual({ Accept: 'application/octet-stream' });
    expect(envelope?.browser.profileMode).toBe('normal');
  });

  it('canonicalizes approved headers so case variants cannot produce duplicates', () => {
    expect(allowedRequestHeaders({
      referer: 'https://first.example.test',
      Referer: 'https://final.example.test',
      'user-agent': 'observed-agent',
      'User-Agent': 'browser-agent',
      Authorization: 'Bearer must-not-be-forwarded',
    })).toEqual({
      Referer: 'https://final.example.test',
      'User-Agent': 'browser-agent',
    });
  });

  it('does not collect request context for an incognito auto-capture without tab metadata', async () => {
    let collectionAttempts = 0;
    const assembler = new ContextAssembler(
      { family: 'chrome', version: '146.0' },
      {
        collect: async () => {
          collectionAttempts += 1;
          return { cookieHeader: 'session=must-not-leave-private-mode' };
        },
      },
    );

    const envelope = await assembler.fromDownload({
      id: 10,
      url: 'https://downloads.example.test/private.zip',
      incognito: true,
    });

    expect(collectionAttempts).toBe(0);
    expect(envelope?.request.cookieHeader).toBeUndefined();
    expect(envelope?.browser.profileMode).toBe('incognito');
  });

  it('creates media envelope fromMediaPage with tab URL as extraction and page URL', async () => {
    const assembler = new ContextAssembler({ family: 'chrome', version: '128.0' });

    const envelope = await assembler.fromMediaPage({
      id: 5,
      url: 'https://www.youtube.com/watch?v=test',
    });

    expect(envelope?.source).toBe('media');
    expect(envelope?.request.url).toBe('https://www.youtube.com/watch?v=test');
    expect(envelope?.request.pageUrl).toBe('https://www.youtube.com/watch?v=test');
  });

  it('uses page URL for media context menu even when srcUrl is a blob URL', async () => {
    const assembler = new ContextAssembler({ family: 'chrome', version: '128.0' });

    const envelope = await assembler.fromContextMenu(
      {
        menuItemId: 'barq-download-media',
        srcUrl: 'blob:https://www.youtube.com/1234-5678',
        pageUrl: 'https://www.youtube.com/watch?v=test',
      },
      { id: 8, url: 'https://www.youtube.com/watch?v=test' },
    );

    expect(envelope?.source).toBe('media');
    expect(envelope?.request.url).toBe('https://www.youtube.com/watch?v=test');
    expect(envelope?.request.pageUrl).toBe('https://www.youtube.com/watch?v=test');
  });

  it('preserves direct context-menu source for normal link menu items', async () => {
    const assembler = new ContextAssembler({ family: 'chrome', version: '128.0' });

    const envelope = await assembler.fromContextMenu({
      menuItemId: 'barq-download-link',
      linkUrl: 'https://example.com/file.zip',
    });

    expect(envelope?.source).toBe('context-menu');
    expect(envelope?.request.url).toBe('https://example.com/file.zip');
  });

  it('returns undefined fromMediaPage when tab URL is not HTTP/HTTPS', async () => {
    const assembler = new ContextAssembler({ family: 'chrome', version: '128.0' });

    expect(await assembler.fromMediaPage({ url: 'chrome://settings' })).toBeUndefined();
    expect(await assembler.fromMediaPage(undefined)).toBeUndefined();
  });
});

describe('cookieQueryForNormalProfile', () => {
  it('falls back to a URL-only query when auto-capture has no tab or cookie-store metadata', () => {
    expect(cookieQueryForNormalProfile('https://downloads.example.test/archive.zip')).toEqual({
      url: 'https://downloads.example.test/archive.zip',
    });
  });

  it('rejects incognito profiles even when a cookie store is present', () => {
    expect(cookieQueryForNormalProfile(
      'https://downloads.example.test/private.zip',
      { incognito: true, cookieStoreId: 'firefox-private' },
    )).toBeUndefined();
  });

  it.each([
    'file:///tmp/archive.zip',
    'not a valid URL',
  ])('rejects non-HTTP or malformed URL %s before any cookie query can be issued', (url) => {
    expect(cookieQueryForNormalProfile(url)).toBeUndefined();
  });
});
