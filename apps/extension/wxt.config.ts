import { defineConfig } from 'wxt';

export default defineConfig({
  manifestVersion: 3,
  srcDir: '.',
  manifest: ({ browser }) => ({
    name: 'Barq Browser Integration',
    short_name: 'Barq',
    description: 'Send downloads and pages securely to Barq.',
    minimum_chrome_version: browser === 'firefox' ? undefined : '120',
    permissions: [
      'nativeMessaging', 'contextMenus', 'storage', 'alarms',
      'activeTab', 'downloads',
    ],
    optional_permissions: ['cookies'],
    optional_host_permissions: ['http://*/*', 'https://*/*'],
    icons: {
      16: 'icons/icon-16.png',
      32: 'icons/icon-32.png',
      48: 'icons/icon-48.png',
      128: 'icons/icon-128.png',
    },
    action: {
      default_title: 'Barq',
      default_icon: {
        16: 'icons/icon-16.png',
        32: 'icons/icon-32.png',
        48: 'icons/icon-48.png',
      },
    },
    browser_specific_settings: browser === 'firefox' ? {
      gecko: {
        id: 'integration@barq.app',
        strict_min_version: '128.0',
      },
    } : undefined,
  }),
});
