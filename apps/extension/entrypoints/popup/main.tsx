import { render } from 'preact';
import { useState, useEffect } from 'preact/hooks';
import { browser } from 'wxt/browser';
import { sitePermissionPattern } from '@barq/browser-core';

const AUTO_CAPTURE_ENABLED = 'autoCaptureEnabled';

interface CookiePermissionTarget {
  pattern: string;
  hostname: string;
}

function App() {
  const [autoCaptureEnabled, setAutoCaptureEnabled] = useState(false);
  const [cookiePermissionTarget, setCookiePermissionTarget] = useState<CookiePermissionTarget>();
  const [cookieAccessGranted, setCookieAccessGranted] = useState(false);
  const [settingError, setSettingError] = useState('');

  useEffect(() => {
    void loadAutoCaptureSetting(setAutoCaptureEnabled, setSettingError);
    void loadCookiePermissionTarget(
      setCookiePermissionTarget,
      setCookieAccessGranted,
      setSettingError,
    );
  }, []);

  const updateAutoCapture = async (event: Event) => {
    const enabled = (event.currentTarget as HTMLInputElement).checked;
    setAutoCaptureEnabled(enabled);
    setSettingError('');

    try {
      await browser.storage.local.set({ [AUTO_CAPTURE_ENABLED]: enabled });
    } catch {
      setAutoCaptureEnabled(!enabled);
      setSettingError('Could not save this setting.');
    }
  };

  const requestCookieAccess = async () => {
    if (!cookiePermissionTarget) {
      setSettingError('Open an HTTP or HTTPS page to enable its optional cookie access.');
      return;
    }

    setSettingError('');
    try {
      const granted = await browser.permissions.request({
        permissions: ['cookies'],
        origins: [cookiePermissionTarget.pattern],
      });
      if (!granted) {
        setSettingError('Cookie access was not granted. Downloads will still use the browser fallback.');
        return;
      }
      setCookieAccessGranted(true);
    } catch {
      setSettingError('Could not request optional cookie access for this site.');
    }
  };

  return (
    <div style={{ width: '300px', padding: '16px', fontFamily: 'sans-serif' }}>
      <h2>Barq Integration</h2>
      <label style={{ display: 'block', lineHeight: '1.5' }}>
        <input checked={autoCaptureEnabled} onChange={updateAutoCapture} type="checkbox" />
        {' '}Automatically capture eligible downloads
      </label>
      <p style={{ fontSize: '12px', color: '#666' }}>
        Barq leaves small files and streaming manifests in the browser.
      </p>
      <button
        disabled={!cookiePermissionTarget || cookieAccessGranted}
        onClick={requestCookieAccess}
        type="button"
      >
        {cookieAccessGranted
          ? `Cookie access enabled for ${cookiePermissionTarget?.hostname ?? 'this site'}`
          : `Allow optional cookie access for ${cookiePermissionTarget?.hostname ?? 'this site'}`}
      </button>
      <p style={{ fontSize: '12px', color: '#666' }}>
        This is requested only for the current site and helps with authenticated downloads.
      </p>
      {settingError && <p role="alert">{settingError}</p>}
      <p style={{ fontSize: '12px', marginTop: '16px', color: '#666' }}>Version 1.0.0</p>
    </div>
  );
}

async function loadCookiePermissionTarget(
  setCookiePermissionTarget: (target: CookiePermissionTarget | undefined) => void,
  setCookieAccessGranted: (granted: boolean) => void,
  setSettingError: (message: string) => void,
): Promise<void> {
  try {
    const [activeTab] = await browser.tabs.query({ active: true, currentWindow: true });
    const target = activeTab?.url ? cookiePermissionTargetFor(activeTab.url) : undefined;
    setCookiePermissionTarget(target);
    if (!target) return;

    const granted = await browser.permissions.contains({
      permissions: ['cookies'],
      origins: [target.pattern],
    });
    setCookieAccessGranted(granted);
  } catch {
    setSettingError('Could not determine the active site for optional cookie access.');
  }
}

function cookiePermissionTargetFor(url: string): CookiePermissionTarget | undefined {
  const pattern = sitePermissionPattern(url);
  if (!pattern) return undefined;
  return { pattern, hostname: new URL(url).hostname };
}

async function loadAutoCaptureSetting(
  setAutoCaptureEnabled: (enabled: boolean) => void,
  setSettingError: (message: string) => void,
): Promise<void> {
  try {
    const preferences = await browser.storage.local.get(AUTO_CAPTURE_ENABLED);
    setAutoCaptureEnabled(preferences[AUTO_CAPTURE_ENABLED] === true);
  } catch {
    setSettingError('Could not load automatic capture settings.');
  }
}

render(<App />, document.getElementById('app')!);
