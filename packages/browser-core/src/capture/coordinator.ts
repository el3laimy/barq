import type { HelloRequest, HostResponse } from '@barq/protocol';
import { ContextAssembler, isHttpUrl } from '../context/assembler';
import { NativeClient, NativeClientError, type NativeClientErrorCode } from '../native/client';
import type { BrowserDownload } from '../context/assembler';
import type { PendingCapture, PendingCaptureStore } from './pending';

const PAUSE_TIMEOUT_MS = 600;

export interface BrowserDownloads {
  pause(downloadId: number): Promise<void>;
  cancel(downloadId: number): Promise<void>;
  resume(downloadId: number): Promise<void>;
  find(downloadId: number): Promise<BrowserDownload | undefined>;
}

export type CaptureOutcome =
  | { status: 'ignored' }
  | { status: 'handed-off'; transferId: string }
  | { status: 'cancel-pending'; transferId: string }
  | { status: 'browser-fallback'; reason: CaptureFailureReason }
  | { status: 'resume-failed'; reason: CaptureFailureReason };

export type CaptureFailureReason = NativeClientErrorCode | 'PAUSE_TIMEOUT' | 'HOST_REJECTED' | 'CANCEL_FAILED';

export class CaptureCoordinator {
  public constructor(private readonly dependencies: CaptureCoordinatorDependencies) {}

  public async capture(download: BrowserDownload): Promise<CaptureOutcome> {
    if (!isHttpUrl(download.url)) return { status: 'ignored' };

    let paused = false;
    let pauseTask: Promise<void> | undefined;
    try {
      await this.dependencies.pendingCaptures.save(observedCapture(download.id));
      pauseTask = this.dependencies.downloads.pause(download.id);
      await pauseBeforeDeadline(pauseTask);
      paused = true;
      await this.dependencies.pendingCaptures.save(pausedCapture(download.id));
      const envelope = await this.dependencies.assembler.fromDownload(download);
      if (!envelope) return this.resumeBrowser(download.id, 'HOST_REJECTED');

      const hostResponse = await this.dependencies.nativeClient.prepareCapture(
        envelope,
        this.dependencies.createHello(),
      );
      if (hostResponse.status !== 'accepted' || !hostResponse.durable) {
        return this.resumeBrowser(download.id, rejectionReason(hostResponse));
      }

      return this.cancelAfterDurableAcceptance(download.id, hostResponse.transferId);
    } catch (reason) {
      const failure = failureReason(reason);
      if (!paused) {
        if (reason instanceof PauseTimeoutError && pauseTask) {
          void this.resumeWhenLatePauseCompletes(download.id, pauseTask);
        } else {
          await this.clearUnacceptedCapture(download.id);
        }
        return { status: 'browser-fallback', reason: failure };
      }
      return this.resumeBrowser(download.id, failure);
    }
  }

  public async recover(): Promise<void> {
    const captures = await this.dependencies.pendingCaptures.list();
    for (const capture of captures) await this.recoverCapture(capture);
  }

  private async recoverCapture(capture: PendingCapture): Promise<void> {
    try {
      const download = await this.dependencies.downloads.find(capture.downloadId);
      if (!download) {
        await this.dependencies.pendingCaptures.remove(capture.downloadId);
      } else if (capture.state === 'accepted') {
        await this.dependencies.downloads.cancel(capture.downloadId);
        await this.dependencies.pendingCaptures.remove(capture.downloadId);
      } else if (download.state === 'in_progress' && download.paused) {
        await this.dependencies.downloads.resume(capture.downloadId);
        await this.dependencies.pendingCaptures.remove(capture.downloadId);
      } else {
        await this.dependencies.pendingCaptures.remove(capture.downloadId);
      }
    } catch {
      // Keep the marker so the next startup/alarm can retry a browser API race.
    }
  }

  private async resumeBrowser(
    downloadId: number,
    reason: CaptureFailureReason,
  ): Promise<CaptureOutcome> {
    try {
      await this.dependencies.downloads.resume(downloadId);
    } catch {
      return { status: 'resume-failed', reason };
    }

    try {
      await this.dependencies.pendingCaptures.remove(downloadId);
    } catch {
      // Recovery can retry cleanup; the browser download has already resumed.
    }
    return { status: 'browser-fallback', reason };
  }

  private async cancelAfterDurableAcceptance(
    downloadId: number,
    transferId: string,
  ): Promise<CaptureOutcome> {
    let acceptedMarkerSaved = await this.saveAcceptedMarker(downloadId);
    try {
      await this.dependencies.downloads.cancel(downloadId);
    } catch {
      if (!acceptedMarkerSaved) acceptedMarkerSaved = await this.saveAcceptedMarker(downloadId);
      if (!acceptedMarkerSaved) {
        // Without a durable accepted marker we cannot safely leave a paused item
        // behind. Favor the user's browser download over an unrecoverable stall.
        return this.resumeBrowser(downloadId, 'CANCEL_FAILED');
      }
      // The native host has a durable item and recovery can retry cancellation.
      return { status: 'cancel-pending', transferId };
    }

    await this.clearAcceptedCapture(downloadId);
    return { status: 'handed-off', transferId };
  }

  private async saveAcceptedMarker(downloadId: number): Promise<boolean> {
    try {
      await this.dependencies.pendingCaptures.save(acceptedCapture(downloadId));
      return true;
    } catch {
      return false;
    }
  }

  private async resumeWhenLatePauseCompletes(
    downloadId: number,
    pauseTask: Promise<void>,
  ): Promise<void> {
    let pauseCompleted = false;
    try {
      await pauseTask;
      pauseCompleted = true;
      await this.dependencies.downloads.resume(downloadId);
      await this.clearUnacceptedCapture(downloadId);
    } catch {
      if (!pauseCompleted) await this.clearUnacceptedCapture(downloadId);
      // If resume failed after a late pause, keep the marker for alarm/startup recovery.
    }
  }

  private async clearUnacceptedCapture(downloadId: number): Promise<void> {
    try {
      await this.dependencies.pendingCaptures.remove(downloadId);
    } catch {
      // The recovery pass can remove an observed marker when browser APIs are available again.
    }
  }

  private async clearAcceptedCapture(downloadId: number): Promise<void> {
    try {
      await this.dependencies.pendingCaptures.remove(downloadId);
    } catch {
      // Retaining accepted state is safer than resuming after a completed handoff.
    }
  }
}

export interface CaptureCoordinatorDependencies {
  downloads: BrowserDownloads;
  assembler: ContextAssembler;
  nativeClient: NativeClient;
  pendingCaptures: PendingCaptureStore;
  createHello(): HelloRequest;
}

function observedCapture(downloadId: number) {
  return { downloadId, state: 'observed' as const, createdAt: Date.now() };
}

function pausedCapture(downloadId: number) {
  return { downloadId, state: 'paused' as const, createdAt: Date.now() };
}

function acceptedCapture(downloadId: number) {
  return { downloadId, state: 'accepted' as const, createdAt: Date.now() };
}

function rejectionReason(response: HostResponse): CaptureFailureReason {
  return response.status === 'rejected' ? response.code : 'HOST_REJECTED';
}

function failureReason(reason: unknown): CaptureFailureReason {
  if (reason instanceof NativeClientError) return reason.code;
  if (reason instanceof PauseTimeoutError) return 'PAUSE_TIMEOUT';
  return 'CANCEL_FAILED';
}

function pauseBeforeDeadline(pause: Promise<void>): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new PauseTimeoutError()), PAUSE_TIMEOUT_MS);
    pause.then(
      () => {
        clearTimeout(timeout);
        resolve();
      },
      (reason) => {
        clearTimeout(timeout);
        reject(reason);
      },
    );
  });
}

class PauseTimeoutError extends Error {
  public constructor() {
    super('Browser download pause did not complete before its deadline');
  }
}
