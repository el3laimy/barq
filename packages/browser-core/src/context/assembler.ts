import {
  DownloadEnvelopeSchema,
  HelloRequestSchema,
  sanitizeFilename,
  type BrowserInfo,
  type DownloadEnvelope,
  type HelloRequest,
} from '@barq/protocol';

export interface ContextMenuSelection {
  menuItemId?: string | number;
  linkUrl?: string;
  srcUrl?: string;
  pageUrl?: string;
  mediaType?: string;
}

export interface BrowserTabContext {
  id?: number;
  title?: string;
  url?: string;
  incognito?: boolean;
  cookieStoreId?: string;
}

/** A browser.cookies.getAll query that is safe to issue for a normal profile. */
export interface CookieCollectionQuery {
  url: string;
  storeId?: string;
}

export interface BrowserDownload {
  id: number;
  url: string;
  finalUrl?: string;
  referrer?: string;
  filename?: string;
  mime?: string;
  fileSize?: number;
  totalBytes?: number;
  incognito?: boolean;
  cookieStoreId?: string;
  tabId?: number;
  state?: string;
  paused?: boolean;
  observedHeaders?: Record<string, string>;
}

export interface ScopedRequestContextProvider {
  collect(context: ScopedRequestContextInput): Promise<ScopedRequestContext>;
}

export interface ScopedRequestContextInput {
  url: string;
  tab?: BrowserTabContext;
  observedHeaders?: Record<string, string>;
}

export interface ScopedRequestContext {
  cookieHeader?: string;
  headers?: Record<string, string>;
}

export class ContextAssembler {
  public constructor(
    private readonly browserIdentity: BrowserIdentity,
    private readonly requestContext?: ScopedRequestContextProvider,
  ) {}

  public createHello(extensionVersion: string): HelloRequest {
    return HelloRequestSchema.parse({
      type: 'hello',
      protocols: ['barq.browser.v1'],
      extensionVersion,
      browser: {
        family: this.browserIdentity.family,
        version: this.browserIdentity.version,
      },
      capabilities: ['auto-capture'],
    });
  }

  public async fromMediaPage(
    tab?: BrowserTabContext,
  ): Promise<DownloadEnvelope | undefined> {
    const pageUrl = firstHttpUrl(tab?.url);
    if (!pageUrl) return undefined;

    return this.createEnvelope({
      url: pageUrl,
      pageUrl,
      source: 'media',
      tab,
    });
  }

  public async fromContextMenu(
    selection: ContextMenuSelection,
    tab?: BrowserTabContext,
  ): Promise<DownloadEnvelope | undefined> {
    const isMedia = selection.menuItemId === 'barq-download-media' || Boolean(selection.mediaType);
    const pageUrl = firstHttpUrl(selection.pageUrl, tab?.url);
    const url = isMedia
      ? (pageUrl ?? firstHttpUrl(selection.srcUrl, selection.linkUrl))
      : firstHttpUrl(selection.linkUrl, selection.srcUrl, selection.pageUrl, tab?.url);

    if (!url) return undefined;

    return this.createEnvelope({
      url,
      source: isMedia ? 'media' : 'context-menu',
      referrer: firstHttpUrl(selection.pageUrl, tab?.url),
      pageUrl,
      tab,
    });
  }

  public async fromDownload(download: BrowserDownload): Promise<DownloadEnvelope | undefined> {
    if (!isHttpUrl(download.url)) return undefined;

    const tab = download.cookieStoreId || download.tabId !== undefined || download.incognito === true
      ? {
          ...(download.cookieStoreId ? { cookieStoreId: download.cookieStoreId } : {}),
          ...(download.tabId === undefined ? {} : { id: download.tabId }),
          ...(download.incognito === undefined ? {} : { incognito: download.incognito }),
        }
      : undefined;

    return this.createEnvelope({
      url: download.url,
      finalUrl: firstHttpUrl(download.finalUrl),
      referrer: firstHttpUrl(download.referrer),
      source: 'auto-download',
      download,
      tab,
      observedHeaders: download.observedHeaders,
      idempotencySeed: [download.id, download.url, download.finalUrl ?? ''].join('|'),
    });
  }

  private async createEnvelope(input: EnvelopeInput): Promise<DownloadEnvelope> {
    const profileMode = profileModeFor(input);
    const requestContext = await this.collectRequestContext(input, profileMode);
    const idempotencyKey = input.idempotencySeed
      ? await sha256(input.idempotencySeed)
      : randomIdempotencyKey();

    return DownloadEnvelopeSchema.parse({
      protocol: 'barq.browser.v1',
      requestId: crypto.randomUUID(),
      idempotencyKey,
      createdAt: new Date().toISOString(),
      source: input.source,
      request: {
        url: input.url,
        ...(input.finalUrl ? { finalUrl: input.finalUrl } : {}),
        ...(input.referrer ? { referrer: input.referrer } : {}),
        ...(input.pageUrl ? { pageUrl: input.pageUrl } : {}),
        headers: allowedRequestHeaders({
          ...input.observedHeaders,
          ...requestContext.headers,
        }),
        ...(requestContext.cookieHeader ? { cookieHeader: requestContext.cookieHeader } : {}),
      },
      file: buildFileInfo(input.download),
      browser: {
        family: this.browserIdentity.family,
        version: this.browserIdentity.version,
        profileMode,
        ...(input.tab?.cookieStoreId ? { cookieStoreId: input.tab.cookieStoreId } : {}),
        ...(input.tab?.id === undefined ? {} : { tabId: input.tab.id }),
      },
      ...(input.source === 'media' && input.tab?.title
        ? { media: { pageTitle: input.tab.title } }
        : {}),
    });
  }

  private async collectRequestContext(
    input: EnvelopeInput,
    profileMode: DownloadEnvelope['browser']['profileMode'],
  ): Promise<ScopedRequestContext> {
    if (!this.requestContext || profileMode === 'incognito') return {};

    return this.requestContext.collect({
      url: input.url,
      tab: input.tab,
      observedHeaders: input.observedHeaders,
    });
  }
}

export interface BrowserIdentity {
  family: BrowserInfo['family'];
  version: string;
}

interface EnvelopeInput {
  url: string;
  source: DownloadEnvelope['source'];
  finalUrl?: string;
  referrer?: string;
  pageUrl?: string;
  tab?: BrowserTabContext;
  download?: BrowserDownload;
  observedHeaders?: Record<string, string>;
  idempotencySeed?: string;
}

export function detectBrowserIdentity(userAgent: string): BrowserIdentity {
  const match = browserFamilyPatterns().find((pattern) => pattern.expression.test(userAgent));
  return {
    family: match?.family ?? 'chrome',
    version: match?.expression.exec(userAgent)?.[1] ?? 'unknown',
  };
}

export function isHttpUrl(url: string | undefined): url is string {
  if (!url) return false;

  try {
    const parsedUrl = new URL(url);
    return parsedUrl.protocol === 'http:' || parsedUrl.protocol === 'https:';
  } catch {
    return false;
  }
}

/**
 * Returns the narrowest cookie query available for a normal browser profile.
 * A URL-only query is intentional when auto-capture has no tab or cookie-store
 * metadata; private profiles and non-HTTP URLs must never trigger collection.
 */
export function cookieQueryForNormalProfile(
  url: string | undefined,
  tab?: BrowserTabContext,
): CookieCollectionQuery | undefined {
  if (!isHttpUrl(url) || tab?.incognito) return undefined;

  return {
    url,
    ...(tab?.cookieStoreId ? { storeId: tab.cookieStoreId } : {}),
  };
}

export function sitePermissionPattern(url: string | undefined): string | undefined {
  if (!isHttpUrl(url)) return undefined;

  const parsedUrl = new URL(url);
  return `${parsedUrl.protocol}//${parsedUrl.hostname}/*`;
}

const ALLOWED_REQUEST_HEADERS = new Map([
  ['referer', 'Referer'],
  ['user-agent', 'User-Agent'],
  ['origin', 'Origin'],
  ['accept', 'Accept'],
  ['accept-language', 'Accept-Language'],
]);

export function allowedRequestHeaders(headers: Record<string, string>): Record<string, string> {
  const normalizedHeaders = new Map<string, [string, string]>();
  for (const [headerName, value] of Object.entries(headers)) {
    const normalizedName = headerName.toLowerCase();
    const canonicalName = ALLOWED_REQUEST_HEADERS.get(normalizedName);
    if (canonicalName) normalizedHeaders.set(normalizedName, [canonicalName, value]);
  }
  return Object.fromEntries(normalizedHeaders.values());
}

function firstHttpUrl(...urls: Array<string | undefined>): string | undefined {
  return urls.find(isHttpUrl);
}

function buildFileInfo(download: BrowserDownload | undefined) {
  const sanitizedName = download?.filename ? sanitizeFilename(download.filename) : undefined;
  const validSize = knownDownloadSize(download);

  return {
    ...(sanitizedName ? { suggestedName: sanitizedName } : {}),
    ...(download?.mime ? { mimeType: download.mime } : {}),
    ...(validSize === undefined ? {} : { size: validSize }),
  };
}

export function knownDownloadSize(download: Pick<BrowserDownload, 'fileSize' | 'totalBytes'> | undefined): number | undefined {
  const candidate = [download?.fileSize, download?.totalBytes]
    .find((size) => size !== undefined && Number.isFinite(size) && size >= 0);
  return candidate === undefined ? undefined : Math.floor(candidate);
}

function isContainerStore(cookieStoreId: string | undefined): boolean {
  return Boolean(cookieStoreId && cookieStoreId !== 'firefox-default');
}

function profileModeFor(input: EnvelopeInput): DownloadEnvelope['browser']['profileMode'] {
  if (input.tab?.incognito || input.download?.incognito) return 'incognito';
  return isContainerStore(input.tab?.cookieStoreId) ? 'container' : 'normal';
}

function browserFamilyPatterns(): Array<{ family: BrowserInfo['family']; expression: RegExp }> {
  return [
    { family: 'edge', expression: /Edg\/([\d.]+)/ },
    { family: 'opera', expression: /OPR\/([\d.]+)/ },
    { family: 'vivaldi', expression: /Vivaldi\/([\d.]+)/ },
    { family: 'firefox', expression: /Firefox\/([\d.]+)/ },
    { family: 'brave', expression: /Brave\/([\d.]+)/ },
    { family: 'chromium', expression: /Chromium\/([\d.]+)/ },
    { family: 'chrome', expression: /Chrome\/([\d.]+)/ },
  ];
}

function randomIdempotencyKey(): string {
  return crypto.randomUUID().replaceAll('-', '');
}

async function sha256(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}
