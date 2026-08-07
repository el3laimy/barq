import { defineBackground } from 'wxt/sandbox';
import { browser } from 'wxt/browser';
import { NativeClient } from '@barq/browser-core/src/native/client';
import { ContextAssembler } from '@barq/browser-core/src/context/assembler';

export default defineBackground(() => {
  const nativeClient = new NativeClient();
  nativeClient.connectNative();

  browser.runtime.onInstalled.addListener(() => {
    browser.contextMenus.create({
      id: 'barq-download-link',
      title: 'Download with Barq',
      contexts: ['link', 'image', 'video', 'audio', 'selection', 'page']
    });
  });

  browser.contextMenus.onClicked.addListener(async (info, tab) => {
    console.log('Context menu clicked');
    const envelope = await ContextAssembler.fromContextMenu(info, tab);
    // TODO: Send to NativeClient
  });

  browser.downloads.onCreated.addListener((downloadItem) => {
    console.log('Download created');
    // TODO: Hand off to coordinator in Sprint 3
  });

  browser.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === 'barq-recovery') {
      console.log('Recovery alarm triggered');
      // TODO: Implement recovery logic
    }
  });

  // Set up recovery alarm
  browser.alarms.create('barq-recovery', { periodInMinutes: 5 });
});
