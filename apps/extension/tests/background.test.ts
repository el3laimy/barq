import { describe, it, expect, vi } from 'vitest';

vi.mock('wxt/browser', () => ({
  browser: {
    runtime: {
      onInstalled: { addListener: vi.fn() },
      onStartup: { addListener: vi.fn() },
      connectNative: vi.fn(),
      getManifest: () => ({ version: '1.0.0' }),
    },
    alarms: {
      onAlarm: { addListener: vi.fn() },
      create: vi.fn(),
    },
    contextMenus: {
      onClicked: { addListener: vi.fn() },
      removeAll: vi.fn().mockResolvedValue(undefined),
      create: vi.fn(),
    },
    downloads: {
      onCreated: { addListener: vi.fn() },
    },
  },
}));

vi.mock('wxt/sandbox', () => ({
  defineBackground: (fn: () => void) => fn,
}));

describe('Background Service Worker Entrypoint', () => {
  it('should export background initialization function', async () => {
    const backgroundModule = await import('../entrypoints/background');
    expect(backgroundModule.default).toBeDefined();
    expect(typeof backgroundModule.default).toBe('function');
  });
});
