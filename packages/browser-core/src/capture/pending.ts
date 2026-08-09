export type PendingCaptureState = 'observed' | 'paused' | 'accepted';

export interface PendingCapture {
  downloadId: number;
  state: PendingCaptureState;
  createdAt: number;
}

export interface PendingCaptureStore {
  save(capture: PendingCapture): Promise<void>;
  remove(downloadId: number): Promise<void>;
  list(): Promise<PendingCapture[]>;
}
