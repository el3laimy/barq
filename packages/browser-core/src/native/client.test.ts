import { afterEach, describe, expect, it, vi } from 'vitest';
import { NativeClient } from './client';
import {
  FakeNativeRuntime,
  healthyHelloAck,
  validEnvelope,
  validHello,
} from '../test-support/native-host';

describe('NativeClient', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('waits for a durable response with the matching correlation ID', async () => {
    const runtime = new FakeNativeRuntime();
    const client = new NativeClient(runtime);
    const envelope = validEnvelope();
    const handoff = client.prepareCapture(envelope, validHello());

    expect(runtime.applicationNames).toEqual(['app.barq.browser']);
    expect(runtime.port.messages[0]).toEqual(validHello());

    runtime.port.emitMessage(healthyHelloAck());
    await eventually(() => runtime.port.messages.length === 2);
    expect(runtime.port.messages[1]).toMatchObject({
      type: 'prepare_capture',
      correlationId: envelope.requestId,
      envelope,
    });

    let didResolve = false;
    void handoff.then(() => { didResolve = true; });
    runtime.port.emitMessage({
      status: 'accepted',
      correlationId: '22222222-2222-4222-8222-222222222222',
      transferId: '33333333-3333-4333-8333-333333333333',
      durable: true,
    });
    await nextTick();
    expect(didResolve).toBe(false);

    runtime.port.emitMessage({
      status: 'accepted',
      correlationId: envelope.requestId,
      transferId: '33333333-3333-4333-8333-333333333333',
      durable: true,
    });
    await expect(handoff).resolves.toMatchObject({ status: 'accepted', durable: true });
  });

  it('does not send a capture to a host without durable-inbox support', async () => {
    const runtime = new FakeNativeRuntime();
    const client = new NativeClient(runtime);
    const handoff = client.prepareCapture(validEnvelope(), validHello());

    runtime.port.emitMessage({
      ...healthyHelloAck(),
      capabilities: [],
    });

    await expect(handoff).rejects.toMatchObject({ code: 'HOST_UNHEALTHY' });
    expect(runtime.port.messages).toHaveLength(1);
  });

  it('reports a hello timeout when the host does not answer', async () => {
    vi.useFakeTimers();
    const runtime = new FakeNativeRuntime();
    const client = new NativeClient(runtime);
    const connection = client.connect(validHello());

    vi.advanceTimersByTime(1_000);

    await expect(connection).rejects.toMatchObject({ code: 'HELLO_TIMEOUT' });
  });

  it('reports a capture timeout after a healthy host stops responding', async () => {
    vi.useFakeTimers();
    const runtime = new FakeNativeRuntime();
    const client = new NativeClient(runtime);
    const handoff = client.prepareCapture(validEnvelope(), validHello(), 100);

    runtime.port.emitMessage(healthyHelloAck());
    await flushMicrotasks();
    expect(runtime.port.messages).toHaveLength(2);

    vi.advanceTimersByTime(100);

    await expect(handoff).rejects.toMatchObject({ code: 'CAPTURE_TIMEOUT' });
  });
});

async function eventually(condition: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (condition()) return;
    await nextTick();
  }
  throw new Error('Expected condition was not reached');
}

function nextTick(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

async function flushMicrotasks(): Promise<void> {
  for (let iteration = 0; iteration < 4; iteration += 1) await Promise.resolve();
}
