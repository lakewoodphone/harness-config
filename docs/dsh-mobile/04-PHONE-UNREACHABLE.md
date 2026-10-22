# "Safari can't open the page because the server can't be found" — and the server is fine

**2026-10-15, 00:47–00:55 UTC.** The owner, from the iPhone 15 Pro:

> The dsh on my iphone stopped working mid session … now, when I try to open it, it says, Safari
> can't open the page because the server can't be found. It's secratary-cloud.tail93e6e6.ts.net.

He restarted the phone. It worked. **Nothing on the server was wrong, and nothing on the server could
have fixed it.** This file is the runbook so that the next session spends two minutes on it instead of
forty, and does not go looking for a server fault that does not exist.

---

## 1. What that message actually means

*"Safari cannot open the page because the server cannot be found"* is a **name-resolution failure on
the device**. It is not a server fault, not a TLS fault and not the engine:

| the message is | the message is not |
|---|---|
| the phone could not turn `secratary-cloud.tail93e6e6.ts.net` into an address | the server being down |
| the phone's **own** DNS path | Serve, the gate, the engine, the certificate |

That name exists **only through Tailscale MagicDNS**, and on iOS MagicDNS is applied by the Tailscale
app to the active network. When the app's DNS configuration is not applied — a network change, the app
suspended or reclaimed by iOS, a tunnel that dropped and re-established — the name stops resolving
**while the tunnel itself still looks connected**. That is the entire incident, and it has the same
shape as **L326 / H117** on the workstations (*MagicDNS `CorpDNS:false`, tunnel up, the name did not
resolve*).

## 2. The one discriminator — 20 seconds, read-only

```bash
ssh secratary-cloud '
  tailscale status | grep -i iphone                                   # is the phone in the tailnet?
  tailscale serve status                                              # :443 -> 127.0.0.1:3086
  grep -a "client=100.85.105.93" /root/.dsh-phone/gate.log | tail -3  # when did the phone last ARRIVE?
  systemctl show phone-engine phone-gate -p NRestarts --value
  ss -tln | grep -E "3086|3089|:443"
'
```

| reading | verdict | where to go |
|---|---|---|
| phone online/active, front door 200 **from another machine**, last gate hit **old** | **device DNS** — the phone is not delivering the request | §3, on the phone |
| front door not 200, or `3086`/`3089` not listening, or `NRestarts` climbing | server fault | §4 |

A request that never arrives leaves **nothing** in the gate log: `gate.log` is the evidence of arrival,
and its emptiness is the discriminator, not proof of health.

## 3. The fix, on the phone

1. **Tailscale off and on** (app, or Settings → VPN). Re-applies the DNS configuration; usually enough.
2. **Restart the phone.** Measured to work on **2026-10-15**, cleared in about 90 seconds.
3. If the app shows *logged out* or an expired key, sign in again. (Both owner devices' keys are valid
   into 2027; this was not expiry — `Expired=None`, `keyExpiry=2027-03-10`.)

Then confirm from the server that the phone is arriving again (§2, second row of the table). Do not
declare it fixed from the phone's screen alone.

## 4. What was measured during the incident

So the next session does not re-litigate the server. All times UTC, 2026-10-15.

| reading | value |
|---|---|
| gate serving the phone (`client=100.85.105.93`) | `00:47:36` → `00:47:50` — `session/attachment`, `skills/list`, `/dsh-phone-mobile.css`, one asset |
| phone's WireGuard handshake | `00:47:44`, peer `online=True active=True`, rx/tx live **while the phone showed the DNS error** |
| front door from ZABZ-YOGA, same window | `https://secratary-cloud.tail93e6e6.ts.net` → **200**, remote ip `100.73.176.126` |
| `phone-engine` / `phone-gate` restarts since boot (`2026-10-14 01:14`) | **0** / **0** |
| disk, memory, failed units | 68% used; 11.2 GB available; `systemctl --failed` empty |
| **after the restart** — phone arrives again | `00:54:53 GET /` (`token_live=True`), full app boot; **55 requests in the next 10 minutes**; last `01:35:33` |

The server was never the fault. The phone's request set at `00:47:36` was a *reload* of an app that had
already lost its platform, and the handshake at `00:47:44` shows the tunnel was carrying traffic to a
phone whose resolver had stopped answering.

## 5. Traps

1. **`grep` on `/root/.dsh-phone/gate.log` answers wrong.** The file holds **37,638 NUL bytes** in 4.2 MB,
   so plain `grep` classifies it as binary, prints `Binary file … matches`, and **silently stops
   printing matches** — the first attempt at this incident returned 2026-10-14 lines while the file's
   real tail was 2026-10-15. **Always `grep -a`.**
2. **A client IP is not a device.** The gate logs no User-Agent (PAIN P43b); `client=100.85.105.93` is
   the owner's phone only because the tailnet says that address is `iphone-15-pro`, and the authority's
   own netmap calls every Apple device `localhost`.
3. `tailscale serve` rewrites the client to `127.0.0.1` and appends the real address in
   `X-Forwarded-For`; the gate's allow-list keys on that (`03-CLOUD-CUTOVER-PHONE-REGRESSION.md`, trap 2).
4. A phone **off** the tailnet is refused with *"This node does not sign in this device"* — a different
   fault (Tailscale absent or stopped on the device), not this one, and also device-side.
5. **Nothing on the server can detect this class.** Every server-side check is green by construction
   while the owner is locked out; the detector is the owner holding the phone (PAIN P40/P55/P43b).
6. **Do not "fix" this by widening the front door.** The engine is loopback-only and fenced by
   `--trusted-host` on purpose, and the Cloudflare `/phone` route only issues a 302 *into* the tailnet
   — it is not a second way in. An IP-addressed fallback would touch the gate's auth path for a fault
   that is not the server's; rejected 2026-10-15 (see journal D-entry of that date).
