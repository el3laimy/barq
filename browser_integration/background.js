// Background Service Worker for Barq Download Manager Integration

const hostName = "com.barq.downloader";
let port = null;

function connectToHost() {
    port = chrome.runtime.connectNative(hostName);
    port.onDisconnect.addListener(() => {
        if (chrome.runtime.lastError) {
            console.log("Disconnected from Barq Native Host:", chrome.runtime.lastError.message);
        }
        port = null;
    });
}

function ensureConnection() {
    if (!port) {
        connectToHost();
    }
}

// Right-click context menu setup
chrome.runtime.onInstalled.addListener(() => {
    chrome.contextMenus.removeAll(() => {
        chrome.contextMenus.create({
            id: "download_with_barq",
            title: "Download with Barq ⚡",
            contexts: ["link", "video", "audio", "image", "selection"]
        });
    });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
    if (info.menuItemId === "download_with_barq") {
        const url = info.linkUrl || info.srcUrl || info.pageUrl;
        if (url) {
            sendDownloadToHost(url, tab ? tab.url : "");
        }
    }
});

chrome.downloads.onCreated.addListener((downloadItem) => {
    if (downloadItem.state !== "in_progress") return;

    const url = downloadItem.url || "";
    const mime = (downloadItem.mime || "").toLowerCase();

    // Filter out internal URLs & data/blob protocols
    if (url.startsWith("chrome://") || url.startsWith("chrome-extension://") || url.startsWith("data:") || url.startsWith("blob:")) {
        return;
    }

    // Filter out streaming media manifests & video segments to prevent breaking browser video playback
    const streamingFormats = [".m3u8", ".mpd", ".ts", ".m4s", "playlist.m3u8", "manifest"];
    const isStreaming = streamingFormats.some(ext => url.toLowerCase().includes(ext)) || 
                        mime.includes("mpegurl") || mime.includes("dash+xml");

    if (isStreaming) {
        console.log("Preserving browser streaming video playback:", url);
        return;
    }

    // Skip small files < 1MB (1048576 bytes) unless unknown size (-1)
    if (downloadItem.fileSize > 0 && downloadItem.fileSize < 1048576) {
        console.log("Skipping small file:", url);
        return;
    }

    console.log("Intercepting download with Barq:", url);

    // Cancel the browser download and hand over to Barq
    chrome.downloads.cancel(downloadItem.id, () => {
        if (chrome.runtime.lastError) {
            console.error("Cancel error:", chrome.runtime.lastError);
        } else {
            console.log("Download cancelled in browser. Gathering info and sending to Barq...");
            sendDownloadToHost(
                downloadItem.url, 
                downloadItem.referrer || "", 
                downloadItem.filename || "", 
                downloadItem.fileSize || 0
            );
        }
    });
});

async function sendDownloadToHost(url, referrer = "", filename = "", fileSize = 0) {
    ensureConnection();
    
    // Capture cookies
    let cookieString = "";
    try {
        const urlObj = new URL(url);
        const cookies = await chrome.cookies.getAll({ domain: urlObj.hostname });
        cookieString = cookies.map(c => `${c.name}=${c.value}`).join("; ");
    } catch (e) {
        console.error("Failed to get cookies:", e);
    }
    
    // Get user-agent
    const userAgent = navigator.userAgent;

    const message = {
        url: url,
        cookies: cookieString,
        referrer: referrer,
        userAgent: userAgent,
        filename: filename,
        fileSize: fileSize
    };

    try {
        port.postMessage(message);
        console.log("Sent full context to Barq host:", url);
    } catch (e) {
        console.error("Failed to send message to Barq host:", e);
        // Retry connection once
        connectToHost();
        try {
            port.postMessage(message);
            console.log("Successfully sent on retry.");
        } catch (retryError) {
            console.error("Retry failed:", retryError);
        }
    }
}
