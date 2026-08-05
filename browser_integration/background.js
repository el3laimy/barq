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
            contexts: ["link", "video", "audio", "image"]
        });
    });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
    if (info.menuItemId === "download_with_barq") {
        const url = info.linkUrl || info.srcUrl;
        if (url) {
            sendDownloadToHost(url, tab ? tab.url : "");
        }
    }
});

chrome.downloads.onCreated.addListener((downloadItem) => {
    if (downloadItem.state !== "in_progress") return;

    // Filter out internal URLs
    if (downloadItem.url.startsWith("chrome://") || downloadItem.url.startsWith("chrome-extension://") || downloadItem.url.startsWith("data:")) {
        return;
    }

    // Skip small files < 1MB (1048576 bytes)
    // Note: If fileSize is -1, it means size is unknown, so we still intercept it.
    if (downloadItem.fileSize > 0 && downloadItem.fileSize < 1048576) {
        console.log("Skipping small file:", downloadItem.url);
        return;
    }

    console.log("Intercepting download with Barq:", downloadItem.url);

    // Cancel the browser download
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
