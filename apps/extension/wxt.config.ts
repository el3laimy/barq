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
    action: {
      default_title: 'Barq',
      default_popup: 'entrypoints/popup/index.html',
    },
    background: browser === 'firefox'
      ? { scripts: ['entrypoints/background.js'], service_worker: 'entrypoints/background.js' }
      : { service_worker: 'entrypoints/background.js', type: 'module' },
    browser_specific_settings: browser === 'firefox' ? {
      gecko: {
        id: 'integration@barq.app',
        strict_min_version: '128.0',
      },
    } : undefined,
  }),
});
