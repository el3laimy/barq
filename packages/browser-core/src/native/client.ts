import { browser } from 'wxt/browser';

export class NativeClient {
  private port: any = null;
  private readonly appName = 'app.barq.browser';
  private idleTimeout: ReturnType<typeof setTimeout> | null = null;
  private readonly IDLE_TIMEOUT_MS = 60000;

  constructor() {}

  public connectNative() {
    try {
      this.port = browser.runtime.connectNative(this.appName);
      this.port.onMessage.addListener(this.onMessage.bind(this));
      this.port.onDisconnect.addListener(this.onDisconnect.bind(this));
      
      this.hello();
      this.resetIdleTimeout();
    } catch (error) {
      console.error('Failed to connect to native host');
    }
  }

  private hello() {
    this.sendMessage({ type: 'hello', version: '1.0.0' });
  }

  public prepareCapture(correlationId: string, timeoutMs: number = 5000): Promise<void> {
    return new Promise((resolve) => {
      this.resetIdleTimeout();
      this.sendMessage({ type: 'prepare_capture', correlationId });
      
      // Stub for waiting for response
      setTimeout(() => resolve(), timeoutMs);
    });
  }

  private sendMessage(message: any) {
    if (this.port) {
      this.port.postMessage(message);
      this.resetIdleTimeout();
    }
  }

  private onMessage(message: any) {
    this.resetIdleTimeout();
    // Handle incoming messages from native host
  }

  private onDisconnect() {
    this.port = null;
    this.clearIdleTimeout();
    
    if (browser.runtime.lastError) {
      console.error('Native port disconnected with error');
    }
    
    // Attempt reconnect after delay
    setTimeout(() => this.connectNative(), 5000);
  }

  private resetIdleTimeout() {
    this.clearIdleTimeout();
    this.idleTimeout = setTimeout(() => {
      if (this.port) {
        this.port.disconnect();
        this.port = null;
      }
    }, this.IDLE_TIMEOUT_MS);
  }

  private clearIdleTimeout() {
    if (this.idleTimeout) {
      clearTimeout(this.idleTimeout);
      this.idleTimeout = null;
    }
  }
}
