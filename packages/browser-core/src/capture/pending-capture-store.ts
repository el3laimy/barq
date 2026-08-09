import type { PendingCapture, PendingCaptureStore, PendingCaptureState } from './pending';

const PENDING_CAPTURE_PREFIX = 'barq.pending-capture.';
const pendingStates = new Set<PendingCaptureState>(['observed', 'paused', 'accepted']);

export interface KeyValuePersistence {
  readAll(): Promise<Record<string, unknown>>;
  write(key: string, storedValue: unknown): Promise<void>;
  remove(key: string): Promise<void>;
}

export class PersistentPendingCaptureStore implements PendingCaptureStore {
  public constructor(private readonly persistence: KeyValuePersistence) {}

  public async save(capture: PendingCapture): Promise<void> {
    await this.persistence.write(captureKey(capture.downloadId), capture);
  }

  public async remove(downloadId: number): Promise<void> {
    await this.persistence.remove(captureKey(downloadId));
  }

  public async list(): Promise<PendingCapture[]> {
    const storedValues = await this.persistence.readAll();
    return Object.entries(storedValues)
      .filter(([key]) => key.startsWith(PENDING_CAPTURE_PREFIX))
      .flatMap(([, candidate]) => parsePendingCapture(candidate));
  }
}

function captureKey(downloadId: number): string {
  return `${PENDING_CAPTURE_PREFIX}${downloadId}`;
}

function parsePendingCapture(candidate: unknown): PendingCapture[] {
  if (!isPendingCapture(candidate)) return [];
  return [candidate];
}

function isPendingCapture(candidate: unknown): candidate is PendingCapture {
  if (!candidate || typeof candidate !== 'object') return false;

  const storedCapture = candidate as Record<string, unknown>;
  return typeof storedCapture.downloadId === 'number'
    && Number.isInteger(storedCapture.downloadId)
    && typeof storedCapture.createdAt === 'number'
    && Number.isFinite(storedCapture.createdAt)
    && typeof storedCapture.state === 'string'
    && pendingStates.has(storedCapture.state as PendingCaptureState);
}
