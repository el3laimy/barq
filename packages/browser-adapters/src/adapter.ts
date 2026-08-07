import { browser } from 'wxt/browser';

export class BrowserAdapter {
  public static isFirefox(): boolean {
    return /Firefox/.test(navigator.userAgent);
  }

  public static getBrowserName(): string {
    if (this.isFirefox()) {
      return 'firefox';
    }
    return 'chrome';
  }

  public static async getCookies(url: string): Promise<string> {
    if (!browser.cookies) return '';
    try {
      const cookies = await browser.cookies.getAll({ url });
      return cookies.map((c: any) => `${c.name}=${c.value}`).join('; ');
    } catch (e) {
      return '';
    }
  }
}
