import { defineBackground } from 'wxt/sandbox';
import { browser } from 'wxt/browser';
import {
  CaptureCoordinator,
  ContextAssembler,
  NativeClient,
  PersistentPendingCaptureStore,
  cookieQueryForNormalProfile,
  detectBrowserIdentity,
  isEligibleForAutoCapture,
  sitePermissionPattern,
  type BrowserDownload,
  type BrowserDownloads,
  type BrowserTabContext,
  type ContextMenuSelection,
  type KeyValuePersistence,
  type NativeRuntime,
  type ScopedRequestContextProvider,
} from '@barq/browser-core';

const DIRECT_CONTEXT_MENU_ID = 'barq-download-link';
const MEDIA_CONTEXT_MENU_ID = 'barq-download-media';
const RECOVERY_ALARM = 'barq-recovery';
const AUTO_CAPTURE_ENABLED = 'autoCaptureEnabled';

export default defineBackground(() => {
  const contextAssembler = new ContextAssembler(
    detectBrowserIdentity(navigator.userAgent),
    scopedRequestContext(),
  );
  const nativeClient = new NativeClient(nativeRuntime());
  const captureCoordinator = new CaptureCoordinator({
    downloads: browserDownloads(),
    assembler: contextAssembler,
    nativeClient,
    pendingCaptures: new PersistentPendingCaptureStore(pendingCapturePersistence()),
    createHello: () => contextAssembler.createHello(browser.runtime.getManifest().version),
  });

  browser.runtime.onInstalled.addListener(() => {
    void installContextMenu();
    void recoverPendingCaptures(captureCoordinator);
  });
  browser.runtime.onStartup.addListener(() => void recoverPendingCaptures(captureCoordinator));
  browser.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === RECOVERY_ALARM) void recoverPendingCaptures(captureCoordinator);
  });
  browser.alarms.create(RECOVERY_ALARM, { periodInMinutes: 1 });

  browser.contextMenus.onClicked.addListener((selection, tab) => {
    if (selection.menuItemId === DIRECT_CONTEXT_MENU_ID || selection.menuItemId === MEDIA_CONTEXT_MENU_ID) {
      void handOffContextMenu(selection, tab, contextAssembler, nativeClient);
    }
  });

  browser.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === 'barq.analyze_media') {
      void analyzeMediaTab(message.tabId, contextAssembler, nativeClient).then(sendResponse);
      return true;
    }
  });

  browser.downloads.onCreated.addListener((download) => {
    void captureDownload(download, captureCoordinator);
  });
});

function nativeRuntime(): NativeRuntime {
  return {
    connectNative: (hostName) => {
      const port = browser.runtime.connectNative(hostName);
      return {
        postMessage: (message) => port.postMessage(message),
        disconnect: () => port.disconnect(),
        onMessage: { addListener: (listener) => port.onMessage.addListener(listener) },
        onDisconnect: { addListener: (listener) => port.onDisconnect.addListener(listener) },
      };
    },
  };
}

function browserDownloads(): BrowserDownloads {
  return {
    pause: (downloadId: number) => browser.downloads.pause(downloadId),
    cancel: (downloadId: number) => browser.downloads.cancel(downloadId),
    resume: (downloadId: number) => browser.downloads.resume(downloadId),
    find: async (downloadId: number) => (await browser.downloads.search({ id: downloadId }))[0],
  };
}

function pendingCapturePersistence(): KeyValuePersistence {
  const persistenceArea = browser.storage.local;
  return {
    readAll: () => persistenceArea.get(null),
    write: (key, storedValue) => persistenceArea.set({ [key]: storedValue }),
    remove: (key) => persistenceArea.remove(key),
  };
}

function scopedRequestContext(): ScopedRequestContextProvider {
  return {
    collect: async (context) => {
      const cookieHeader = await collectScopedCookies(context.url, context.tab);
      return {
        headers: {
          ...context.observedHeaders,
          'User-Agent': navigator.userAgent,
        },
        ...(cookieHeader ? { cookieHeader } : {}),
      };
    },
  };
}

async function collectScopedCookies(
  url: string,
  tab?: BrowserTabContext,
): Promise<string | undefined> {
  const cookieQuery = cookieQueryForNormalProfile(url, tab);
  if (!cookieQuery || !(await hasScopedCookiePermission(cookieQuery.url))) return undefined;

  const storeId = cookieQuery.storeId ?? await cookieStoreForTab(tab);

  try {
    const cookies = await browser.cookies.getAll(
      storeId ? { url: cookieQuery.url, storeId } : cookieQuery,
    );
    const cookieHeader = cookies
      .sort((left, right) => right.path.length - left.path.length)
      .map((cookie) => `${cookie.name}=${cookie.value}`)
      .join('; ');
    return new TextEncoder().encode(cookieHeader).byteLength <= 64_000
      ? cookieHeader
      : undefined;
  } catch {
    // Permission changes and private-mode policy races must not block the browser download.
    return undefined;
  }
}

async function hasScopedCookiePermission(url: string): Promise<boolean> {
  const origin = sitePermissionPattern(url);
  if (!origin) return false;
  try {
    return await browser.permissions.contains({
      permissions: ['cookies'],
      origins: [origin],
    });
  } catch {
    return false;
  }
}

async function cookieStoreForTab(tab: BrowserTabContext | undefined): Promise<string | undefined> {
  if (tab?.cookieStoreId) return tab.cookieStoreId;
  const tabId = tab?.id;
  if (tabId === undefined) return undefined;

  try {
    const stores = await browser.cookies.getAllCookieStores();
    return stores.find((store) => store.tabIds.includes(tabId))?.id;
  } catch {
    return undefined;
  }
}

async function installContextMenu(): Promise<void> {
  await browser.contextMenus.removeAll();
  browser.contextMenus.create({
    id: DIRECT_CONTEXT_MENU_ID,
    title: 'Download with Barq',
    contexts: ['link', 'image'],
  });
  browser.contextMenus.create({
    id: MEDIA_CONTEXT_MENU_ID,
    title: 'Download media with Barq ⚡',
    contexts: ['page', 'video', 'audio'],
  });
}

async function analyzeMediaTab(
  tabId: number | undefined,
  contextAssembler: ContextAssembler,
  nativeClient: NativeClient,
): Promise<{ ok: boolean; reason?: string }> {
  if (tabId === undefined) return { ok: false, reason: 'invalid_tab' };

  try {
    const tab = await browser.tabs.get(tabId);
    if (!tab?.url) return { ok: false, reason: 'invalid_tab' };

    const envelope = await contextAssembler.fromMediaPage(tab);
    if (!envelope) return { ok: false, reason: 'invalid_page' };

    const response = await nativeClient.prepareCapture(
      envelope,
      contextAssembler.createHello(browser.runtime.getManifest().version),
      2_500,
    );

    if (response.status === 'accepted' && response.durable) {
      await setHandoffBadge('');
      return { ok: true };
    }
    await setHandoffBadge('!');
    return { ok: false, reason: 'handoff_failed' };
  } catch {
    await setHandoffBadge('!');
    return { ok: false, reason: 'native_unavailable' };
  }
}

async function handOffContextMenu(
  selection: ContextMenuSelection,
  tab: BrowserTabContext | undefined,
  contextAssembler: ContextAssembler,
  nativeClient: NativeClient,
): Promise<void> {
  const envelope = await contextAssembler.fromContextMenu(selection, tab);
  if (!envelope) return;

  try {
    const response = await nativeClient.prepareCapture(
      envelope,
      contextAssembler.createHello(browser.runtime.getManifest().version),
      2_500,
    );
    await setHandoffBadge(response.status === 'accepted' && response.durable ? '' : '!');
  } catch {
    // Native failures are surfaced generically; raw host errors may contain private context.
    await setHandoffBadge('!');
  }
}

async function captureDownload(
  download: BrowserDownload,
  captureCoordinator: CaptureCoordinator,
): Promise<void> {
  if (!await autoCaptureEnabled()) return;
  if (!isEligibleForAutoCapture(download)) return;

  const outcome = await captureCoordinator.capture(download);
  if (outcome.status === 'resume-failed' || outcome.status === 'cancel-pending') {
    await setHandoffBadge('!');
  }
}

async function autoCaptureEnabled(): Promise<boolean> {
  try {
    const preferences = await browser.storage.local.get(AUTO_CAPTURE_ENABLED);
    return preferences[AUTO_CAPTURE_ENABLED] === true;
  } catch {
    return false;
  }
}

async function recoverPendingCaptures(captureCoordinator: CaptureCoordinator): Promise<void> {
  try {
    await captureCoordinator.recover();
  } catch {
    await setHandoffBadge('!');
  }
}

function setHandoffBadge(text: string): Promise<void> {
  return browser.action.setBadgeText({ text });
}
