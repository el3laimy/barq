import { afterEach, describe, expect, it, vi } from 'vitest';
import { CaptureCoordinator, type BrowserDownloads } from './coordinator';
import type { PendingCapture, PendingCaptureStore } from './pending';
import { ContextAssembler } from '../context/assembler';
import { NativeClient } from '../native/client';
import {
  FakeNativeRuntime,
  healthyHelloAck,
} from '../test-support/native-host';

describe('CaptureCoordinator', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('cancels only after the host confirms durable acceptance', async () => {
    const runtime = new FakeNativeRuntime();
    const downloads = new FakeDownloads();
    const coordinator = coordinatorFor(runtime, downloads);
    const capture = coordinator.capture(downloadFixture());

    await eventually(() => runtime.port.messages.length === 1);
    expect(downloads.operations).toEqual(['pause']);
    runtime.port.emitMessage(healthyHelloAck());
    await eventually(() => runtime.port.messages.length === 2);
    runtime.port.emitMessage({
      status: 'accepted',
      correlationId: runtime.port.messages[1].type === 'prepare_capture'
        ? runtime.port.messages[1].correlationId
        : '',
      transferId: '33333333-3333-4333-8333-333333333333',
      durable: true,
    });

    await expect(capture).resolves.toEqual({
      status: 'handed-off',
      transferId: '33333333-3333-4333-8333-333333333333',
    });
    expect(downloads.operations).toEqual(['pause', 'cancel']);
  });

  it('resumes the browser when the host rejects the handoff', async () => {
    const runtime = new FakeNativeRuntime();
    const downloads = new FakeDownloads();
    const coordinator = coordinatorFor(runtime, downloads);
    const capture = coordinator.capture(downloadFixture());

    await eventually(() => runtime.port.messages.length === 1);
    runtime.port.emitMessage(healthyHelloAck());
    await eventually(() => runtime.port.messages.length === 2);
    runtime.port.emitMessage({
      status: 'rejected',
      correlationId: runtime.port.messages[1].type === 'prepare_capture'
        ? runtime.port.messages[1].correlationId
        : '',
      code: 'QUEUE_UNAVAILABLE',
      retryable: true,
    });

    await expect(capture).resolves.toEqual({
      status: 'browser-fallback',
      reason: 'QUEUE_UNAVAILABLE',
    });
    expect(downloads.operations).toEqual(['pause', 'resume']);
  });

  it('resumes if a browser pause completes after the capture deadline', async () => {
    vi.useFakeTimers();
    const runtime = new FakeNativeRuntime();
    const downloads = new FakeDownloads();
    const latePause = deferred<void>();
    downloads.pauseResult = latePause.promise;
    const coordinator = coordinatorFor(runtime, downloads);

    const capture = coordinator.capture(downloadFixture());
    await flushMicrotasks();
    expect(downloads.operations).toEqual(['pause']);

    await vi.advanceTimersByTimeAsync(600);
    await expect(capture).resolves.toEqual({
      status: 'browser-fallback',
      reason: 'PAUSE_TIMEOUT',
    });

    latePause.resolve();
    await flushMicrotasks();
    expect(downloads.operations).toEqual(['pause', 'resume']);
  });

  it('keeps durable handoffs pending cancellation instead of resuming them', async () => {
    const runtime = new FakeNativeRuntime();
    const downloads = new FakeDownloads();
    downloads.cancelFailure = new Error('browser cancel failed');
    const pendingCaptures = new MemoryPendingCaptureStore();
    const coordinator = coordinatorFor(runtime, downloads, pendingCaptures);
    const capture = coordinator.capture(downloadFixture());

    await eventually(() => runtime.port.messages.length === 1);
    runtime.port.emitMessage(healthyHelloAck());
    await eventually(() => runtime.port.messages.length === 2);
    runtime.port.emitMessage({
      status: 'accepted',
      correlationId: runtime.port.messages[1].type === 'prepare_capture'
        ? runtime.port.messages[1].correlationId
        : '',
      transferId: '33333333-3333-4333-8333-333333333333',
      durable: true,
    });

    await expect(capture).resolves.toEqual({
      status: 'cancel-pending',
      transferId: '33333333-3333-4333-8333-333333333333',
    });
    expect(downloads.operations).toEqual(['pause', 'cancel']);
    await expect(pendingCaptures.list()).resolves.toMatchObject([{ state: 'accepted' }]);
  });

  it('falls back to the browser if acceptance cannot be journaled for cancellation recovery', async () => {
    const runtime = new FakeNativeRuntime();
    const downloads = new FakeDownloads();
    downloads.cancelFailure = new Error('browser cancel failed');
    const pendingCaptures = new MemoryPendingCaptureStore();
    pendingCaptures.rejectAcceptedWrites = true;
    const coordinator = coordinatorFor(runtime, downloads, pendingCaptures);
    const capture = coordinator.capture(downloadFixture());

    await eventually(() => runtime.port.messages.length === 1);
    runtime.port.emitMessage(healthyHelloAck());
    await eventually(() => runtime.port.messages.length === 2);
    runtime.port.emitMessage({
      status: 'accepted',
      correlationId: runtime.port.messages[1].type === 'prepare_capture'
        ? runtime.port.messages[1].correlationId
        : '',
      transferId: '33333333-3333-4333-8333-333333333333',
      durable: true,
    });

    await expect(capture).resolves.toEqual({
      status: 'browser-fallback',
      reason: 'CANCEL_FAILED',
    });
    expect(downloads.operations).toEqual(['pause', 'cancel', 'resume']);
    await expect(pendingCaptures.list()).resolves.toEqual([]);
  });

  it('retries cancellation for an accepted handoff after a service-worker restart', async () => {
    const runtime = new FakeNativeRuntime();
    const downloads = new FakeDownloads();
    downloads.foundDownload = downloadFixture();
    const pendingCaptures = new MemoryPendingCaptureStore();
    await pendingCaptures.save({ downloadId: 7, state: 'accepted', createdAt: Date.now() });
    const coordinator = coordinatorFor(runtime, downloads, pendingCaptures);

    await coordinator.recover();

    expect(downloads.operations).toEqual(['cancel']);
    await expect(pendingCaptures.list()).resolves.toEqual([]);
  });

  it('resumes a paused capture that never reached durable acceptance', async () => {
    const runtime = new FakeNativeRuntime();
    const downloads = new FakeDownloads();
    downloads.foundDownload = { ...downloadFixture(), paused: true };
    const pendingCaptures = new MemoryPendingCaptureStore();
    await pendingCaptures.save({ downloadId: 7, state: 'paused', createdAt: Date.now() });
    const coordinator = coordinatorFor(runtime, downloads, pendingCaptures);

    await coordinator.recover();

    expect(downloads.operations).toEqual(['resume']);
    await expect(pendingCaptures.list()).resolves.toEqual([]);
  });

  it('keeps an accepted marker when restart recovery cannot cancel yet', async () => {
    const runtime = new FakeNativeRuntime();
    const downloads = new FakeDownloads();
    downloads.foundDownload = downloadFixture();
    downloads.cancelFailure = new Error('browser cancel failed');
    const pendingCaptures = new MemoryPendingCaptureStore();
    await pendingCaptures.save({ downloadId: 7, state: 'accepted', createdAt: Date.now() });
    const coordinator = coordinatorFor(runtime, downloads, pendingCaptures);

    await coordinator.recover();

    expect(downloads.operations).toEqual(['cancel']);
    await expect(pendingCaptures.list()).resolves.toMatchObject([{ state: 'accepted' }]);
  });

  it('fails open when the native host disconnects before acceptance', async () => {
    const runtime = new FakeNativeRuntime();
    const downloads = new FakeDownloads();
    const coordinator = coordinatorFor(runtime, downloads);
    const capture = coordinator.capture(downloadFixture());

    await eventually(() => runtime.port.messages.length === 1);
    runtime.port.disconnect();

    await expect(capture).resolves.toEqual({
      status: 'browser-fallback',
      reason: 'HOST_DISCONNECTED',
    });
    expect(downloads.operations).toEqual(['pause', 'resume']);
  });

});

function coordinatorFor(
  runtime: FakeNativeRuntime,
  downloads: FakeDownloads,
  pendingCaptures: PendingCaptureStore = new MemoryPendingCaptureStore(),
): CaptureCoordinator {
  const assembler = new ContextAssembler({ family: 'chrome', version: '146.0' });
  return new CaptureCoordinator({
    downloads,
    assembler,
    nativeClient: new NativeClient(runtime),
    pendingCaptures,
    createHello: () => assembler.createHello('1.0.0'),
  });
}

function downloadFixture() {
  return {
    id: 7,
    url: 'https://downloads.example.test/archive.zip',
    finalUrl: 'https://cdn.example.test/archive.zip',
    fileSize: 10_000_000,
    state: 'in_progress',
    paused: false,
  };
}

class FakeDownloads implements BrowserDownloads {
  public readonly operations: string[] = [];
  public pauseResult: Promise<void> | undefined;
  public cancelFailure: Error | undefined;
  public foundDownload: ReturnType<typeof downloadFixture> | undefined;

  public async pause(): Promise<void> {
    this.operations.push('pause');
    await this.pauseResult;
  }

  public async cancel(): Promise<void> {
    this.operations.push('cancel');
    if (this.cancelFailure) throw this.cancelFailure;
  }

  public async resume(): Promise<void> {
    this.operations.push('resume');
  }

  public async find() {
    return this.foundDownload;
  }
}

class MemoryPendingCaptureStore implements PendingCaptureStore {
  private readonly captures = new Map<number, PendingCapture>();
  public rejectAcceptedWrites = false;

  public async save(capture: PendingCapture): Promise<void> {
    if (capture.state === 'accepted' && this.rejectAcceptedWrites) {
      throw new Error('persistence unavailable');
    }
    this.captures.set(capture.downloadId, capture);
  }

  public async remove(downloadId: number): Promise<void> {
    this.captures.delete(downloadId);
  }

  public async list(): Promise<PendingCapture[]> {
    return [...this.captures.values()];
  }
}

async function eventually(condition: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (condition()) return;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  throw new Error('Expected condition was not reached');
}

function deferred<T>() {
  let resolve: (value: T | PromiseLike<T>) => void = () => undefined;
  const promise = new Promise<T>((resolveDeferred) => {
    resolve = resolveDeferred;
  });
  return { promise, resolve };
}

async function flushMicrotasks(): Promise<void> {
  for (let iteration = 0; iteration < 4; iteration += 1) await Promise.resolve();
}
