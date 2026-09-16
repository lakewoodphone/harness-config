// Zabz: route ONLY rattlebyte.com through the office server's SSH tunnel.
//
// Why: this laptop's home line (T-Mobile) cannot reach 185.112.144.0/22 at all
// (every port times out) while Google/Cloudflare/1984.is are 100% healthy and
// 8/8 global nodes reach the site. Same Zayo transit works from the office and
// from Hetzner. So the site is fine; this one prefix is unroutable from here.
// Tunnel: ssh -D 127.0.0.1:11080 -> secratary-ts (office LAN).
//
// Everything not matching rattlebyte.com goes DIRECT, so blast radius is one domain.
// Undo: delete the AutoConfigURL value under
//   HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings
function FindProxyForURL(url, host) {
  host = host.toLowerCase();

  if (dnsDomainIs(host, "rattlebyte.com") || host === "rattlebyte.com") {
    return "SOCKS5 127.0.0.1:11080; SOCKS 127.0.0.1:11080; DIRECT";
  }
  // Literal IP of the site, in case anything addresses it directly.
  if (isInNet(host, "185.112.145.212", "255.255.255.255")) {
    return "SOCKS5 127.0.0.1:11080; DIRECT";
  }
  return "DIRECT";
}
