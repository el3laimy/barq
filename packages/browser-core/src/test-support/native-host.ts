import { DownloadEnvelopeSchema, type DownloadEnvelope, type HelloRequest } from '@barq/protocol';
import type { HostRequest } from '@barq/protocol';
import type { NativeEvent, NativePort, NativeRuntime } from '../native/client';

export class FakeNativePort implements NativePort {
  public readonly messages: HostRequest[] = [];
  public readonly onMessage = new FakeEvent<unknown>();
  public readonly onDisconnect = new FakeEvent<unknown>();

  public postMessage(message: HostRequest): void {
    this.messages.push(message);
  }

  public disconnect(): void {
    this.onDisconnect.emit(undefined);
  }

  public emitMessage(message: unknown): void {
    this.onMessage.emit(message);
  }
}

export class FakeNativeRuntime implements NativeRuntime {
  public readonly port = new FakeNativePort();
  public readonly applicationNames: string[] = [];

  public connectNative(applicationName: string): NativePort {
    this.applicationNames.push(applicationName);
    return this.port;
  }
}

export class FakeEvent<Payload> implements NativeEvent<Payload> {
  private readonly listeners: Array<(payload: Payload) => void> = [];

  public addListener(listener: (payload: Payload) => void): void {
    this.listeners.push(listener);
  }

  public emit(payload: Payload): void {
    for (const listener of this.listeners) listener(payload);
  }
}

export function validHello(): HelloRequest {
  return {
    type: 'hello',
    protocols: ['barq.browser.v1'],
    extensionVersion: '1.0.0',
    browser: { family: 'chrome', version: '146.0' },
    capabilities: ['auto-capture'],
  };
}

export function validEnvelope(): DownloadEnvelope {
  return DownloadEnvelopeSchema.parse({
    protocol: 'barq.browser.v1',
    requestId: '11111111-1111-4111-8111-111111111111',
    idempotencyKey: 'a'.repeat(32),
    createdAt: '2026-08-08T00:00:00.000Z',
    source: 'auto-download',
    request: { url: 'https://downloads.example.test/archive.zip', headers: {} },
    file: { suggestedName: 'archive.zip', size: 10_000_000 },
    browser: { family: 'chrome', version: '146.0', profileMode: 'normal' },
  });
}

export function healthyHelloAck() {
  return {
    type: 'hello_ack' as const,
    protocol: 'barq.browser.v1' as const,
    hostVersion: '1.0.0',
    healthy: true,
    capabilities: ['durable-inbox'],
    limits: { maxMessageBytes: 900_000, maxCookieBytes: 64_000 },
  };
}
