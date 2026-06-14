// Overwritten on VPS deploy when YTS_API_URL / SITE_NAME secrets are set.
window.YTS_CONFIG = {
  apiBase: "/api/v2",
  siteName: "YTS",
  siteTagline: "HD movies at the smallest file size",
  trackers: [
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.openbittorrent.com:80",
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://tracker.coppersurfer.tk:6969",
  ],
};
