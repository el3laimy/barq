export interface DownloadEnvelope {
  url: string;
  referrer?: string;
  cookies?: string;
  userAgent?: string;
  pageTitle?: string;
  pageUrl?: string;
}

export class ContextAssembler {
  public static async fromContextMenu(info: any, tab?: any): Promise<DownloadEnvelope> {
    const url = info.linkUrl || info.srcUrl || info.selectionText || info.pageUrl || '';
    
    return {
      url,
      referrer: info.pageUrl,
      pageTitle: tab?.title,
      pageUrl: tab?.url,
    };
  }

  public static async fromDownloadItem(item: any): Promise<DownloadEnvelope> {
    return {
      url: item.url,
      referrer: item.referrer,
      // Further enrichment can be done here
    };
  }
}
