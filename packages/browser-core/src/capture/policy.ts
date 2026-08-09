import type { BrowserDownload } from '../context/assembler';
import { isHttpUrl, knownDownloadSize } from '../context/assembler';

const MINIMUM_AUTO_CAPTURE_BYTES = 1024 * 1024;
const STREAMING_MANIFEST = /\.(?:m3u8|mpd)(?:\?|$)/i;

export function isEligibleForAutoCapture(download: BrowserDownload): boolean {
  if (!isHttpUrl(download.url)) return false;
  if (download.incognito) return false;
  if (isStreamingManifest(download.url)
    || isStreamingManifest(download.finalUrl)
    || isStreamingManifest(download.filename)
    || isStreamingMimeType(download.mime)) return false;
  return !hasKnownSmallSize(knownDownloadSize(download));
}

function isStreamingManifest(url: string | undefined): boolean {
  return Boolean(url && STREAMING_MANIFEST.test(url));
}

function isStreamingMimeType(mimeType: string | undefined): boolean {
  const normalized = mimeType?.split(';', 1)[0]?.trim().toLowerCase();
  return normalized === 'application/dash+xml'
    || normalized === 'application/vnd.apple.mpegurl'
    || normalized === 'application/x-mpegurl';
}

function hasKnownSmallSize(fileSize: number | undefined): boolean {
  return fileSize !== undefined && fileSize >= 0 && fileSize < MINIMUM_AUTO_CAPTURE_BYTES;
}
