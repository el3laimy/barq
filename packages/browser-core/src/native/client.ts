import {
  HelloAckSchema,
  HelloRequestSchema,
  HostResponseSchema,
  PrepareCaptureRequestSchema,
  type HelloAck,
  type HelloRequest,
  type HostRequest,
  type HostResponse,
  type RejectedResponse,
  type DownloadEnvelope,
} from '@barq/protocol';

const HOST_NAME = 'app.barq.browser';
const HELLO_TIMEOUT_MS = 1_000;
const PORT_LEASE_MS = 60_000;

export interface NativePort {
  postMessage(message: HostRequest): void;
  disconnect(): void;
  onMessage: NativeEvent<unknown>;
  onDisconnect: NativeEvent<unknown>;
}

export interface NativeEvent<Payload> {
  addListener(listener: (payload: Payload) => void): void;
}

export interface NativeRuntime {
  connectNative(applicationName: string): NativePort;
}

export type NativeClientErrorCode =
  | RejectedResponse['code']
  | 'HOST_NOT_REGISTERED'
  | 'HOST_DISCONNECTED'
  | 'HOST_UNHEALTHY'
  | 'HOST_LIMIT_EXCEEDED'
  | 'HELLO_TIMEOUT'
  | 'CAPTURE_TIMEOUT';

export class NativeClientError extends Error {
  public constructor(public readonly code: NativeClientErrorCode) {
    super(`Native host request failed: ${code}`);
    this.name = 'NativeClientError';
  }
}

export class NativeClient {
  private port: NativePort | undefined;
  private helloAck: HelloAck | undefined;
  private helloPending: PendingHello | undefined;
  private readonly pendingResponses = new Map<string, PendingResponse>();
  private leaseTimer: ReturnType<typeof setTimeout> | undefined;

  public constructor(private readonly runtime: NativeRuntime) {}

  public async connect(hello: HelloRequest): Promise<HelloAck> {
    const validatedHello = HelloRequestSchema.parse(hello);
    if (this.helloAck) return this.helloAck;
    if (this.helloPending) return this.helloPending.promise;

    this.openPort();
    return this.sendHello(validatedHello);
  }

  public async prepareCapture(
    envelope: DownloadEnvelope,
    hello: HelloRequest,
    timeoutMs = 1_500,
  ): Promise<HostResponse> {
    const helloAck = await this.connect(hello);
    if (!helloAck.healthy || !helloAck.capabilities.includes('durable-inbox')) {
      throw new NativeClientError('HOST_UNHEALTHY');
    }
    const request = PrepareCaptureRequestSchema.parse({
      type: 'prepare_capture',
      correlationId: envelope.requestId,
      envelope,
    });
    if (!fitsHostLimits(request, helloAck)) throw new NativeClientError('HOST_LIMIT_EXCEEDED');
    const response = this.waitForResponse(request.correlationId, timeoutMs);
    this.renewPortLease();
    this.sendRequest(request, request.correlationId);
    return response;
  }

  private openPort(): void {
    this.closeExistingPort();
    let connectedPort: NativePort;
    try {
      connectedPort = this.runtime.connectNative(HOST_NAME);
    } catch {
      throw new NativeClientError('HOST_NOT_REGISTERED');
    }

    this.port = connectedPort;
    connectedPort.onMessage.addListener((message) => {
      if (this.port === connectedPort) this.receiveMessage(message);
    });
    connectedPort.onDisconnect.addListener(() => {
      if (this.port === connectedPort) this.disconnect();
    });
  }

  private sendHello(hello: HelloRequest): Promise<HelloAck> {
    const pendingHello = this.waitForHello();
    this.sendRequest(hello);
    return pendingHello;
  }

  private sendRequest(request: HostRequest, correlationId?: string): void {
    const activePort = this.port;
    if (!activePort) {
      this.failRequest(correlationId, 'HOST_DISCONNECTED');
      return;
    }

    try {
      activePort.postMessage(request);
    } catch {
      this.failRequest(correlationId, 'HOST_DISCONNECTED');
    }
  }

  private receiveMessage(message: unknown): void {
    const helloAck = HelloAckSchema.safeParse(message);
    if (helloAck.success) {
      this.acceptHello(helloAck.data);
      return;
    }

    const hostResponse = HostResponseSchema.safeParse(message);
    if (hostResponse.success) this.acceptResponse(hostResponse.data);
  }

  private waitForHello(): Promise<HelloAck> {
    let resolveHello: (ack: HelloAck) => void = () => undefined;
    let rejectHello: (reason: NativeClientError) => void = () => undefined;
    const promise = new Promise<HelloAck>((resolve, reject) => {
      resolveHello = resolve;
      rejectHello = reject;
    });
    const timeout = setTimeout(() => {
      this.helloPending = undefined;
      rejectHello(new NativeClientError('HELLO_TIMEOUT'));
      const activePort = this.port;
      this.disconnect();
      activePort?.disconnect();
    }, HELLO_TIMEOUT_MS);

    this.helloPending = { promise, resolveHello, rejectHello, timeout };
    return promise;
  }

  private waitForResponse(correlationId: string, timeoutMs: number): Promise<HostResponse> {
    let resolveResponse: (response: HostResponse) => void = () => undefined;
    let rejectResponse: (reason: NativeClientError) => void = () => undefined;
    const promise = new Promise<HostResponse>((resolve, reject) => {
      resolveResponse = resolve;
      rejectResponse = reject;
    });
    const timeout = setTimeout(() => {
      this.pendingResponses.delete(correlationId);
      rejectResponse(new NativeClientError('CAPTURE_TIMEOUT'));
    }, timeoutMs);

    this.pendingResponses.set(correlationId, { resolveResponse, rejectResponse, timeout });
    return promise;
  }

  private acceptHello(helloAck: HelloAck): void {
    if (!this.helloPending) return;
    clearTimeout(this.helloPending.timeout);
    this.helloAck = helloAck;
    this.helloPending.resolveHello(helloAck);
    this.helloPending = undefined;
    this.renewPortLease();
  }

  private acceptResponse(response: HostResponse): void {
    const pending = this.pendingResponses.get(response.correlationId);
    if (pending) {
      clearTimeout(pending.timeout);
      this.pendingResponses.delete(response.correlationId);
      pending.resolveResponse(response);
      this.renewPortLease();
      return;
    }

    if (response.status === 'rejected' && this.helloPending) {
      this.failHello(response.code);
    }
  }

  private failRequest(correlationId: string | undefined, code: NativeClientErrorCode): void {
    if (correlationId) {
      const pending = this.pendingResponses.get(correlationId);
      if (pending) {
        clearTimeout(pending.timeout);
        this.pendingResponses.delete(correlationId);
        pending.rejectResponse(new NativeClientError(code));
      }
      return;
    }

    this.failHello(code);
  }

  private failHello(code: NativeClientErrorCode): void {
    if (!this.helloPending) return;
    clearTimeout(this.helloPending.timeout);
    this.helloPending.rejectHello(new NativeClientError(code));
    this.helloPending = undefined;
  }

  private disconnect(): void {
    this.port = undefined;
    this.helloAck = undefined;
    this.clearPortLease();
    this.failHello('HOST_DISCONNECTED');
    for (const [correlationId, pending] of this.pendingResponses) {
      clearTimeout(pending.timeout);
      pending.rejectResponse(new NativeClientError('HOST_DISCONNECTED'));
      this.pendingResponses.delete(correlationId);
    }
  }

  private closeExistingPort(): void {
    const existingPort = this.port;
    if (!existingPort) return;

    this.disconnect();
    existingPort.disconnect();
  }

  private renewPortLease(): void {
    this.clearPortLease();
    this.leaseTimer = setTimeout(() => {
      const leasedPort = this.port;
      this.disconnect();
      leasedPort?.disconnect();
    }, PORT_LEASE_MS);
  }

  private clearPortLease(): void {
    if (this.leaseTimer) clearTimeout(this.leaseTimer);
    this.leaseTimer = undefined;
  }
}

interface PendingHello {
  promise: Promise<HelloAck>;
  resolveHello: (ack: HelloAck) => void;
  rejectHello: (reason: NativeClientError) => void;
  timeout: ReturnType<typeof setTimeout>;
}

interface PendingResponse {
  resolveResponse: (response: HostResponse) => void;
  rejectResponse: (reason: NativeClientError) => void;
  timeout: ReturnType<typeof setTimeout>;
}

function fitsHostLimits(request: HostRequest, helloAck: HelloAck): boolean {
  const encoder = new TextEncoder();
  const messageBytes = encoder.encode(JSON.stringify(request)).byteLength;
  const cookieBytes = request.type === 'prepare_capture'
    ? encoder.encode(request.envelope.request.cookieHeader ?? '').byteLength
    : 0;
  return messageBytes <= helloAck.limits.maxMessageBytes
    && cookieBytes <= helloAck.limits.maxCookieBytes;
}
