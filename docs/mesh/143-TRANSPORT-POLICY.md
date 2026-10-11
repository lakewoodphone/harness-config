# 143 - TRANSPORT POLICY: LAN, Tailscale, Cloudflare
Owner requirement, 2026-10-11, verbatim: *"we also want robust lan, tailscale and cloudflare setup,
obviously lan is fastest for stuff on the same network. but we can't just rely on tailscale for
everything, what if it goes wrong, we should have robust cloudflare scripts and setups also."*
This is the policy the routing scripts implement. It exists because a single-transport dependency is
the failure mode this estate keeps paying for: when the one path breaks, everything that used it is
down at once and nothing says why.
## The three transports, and what each is actually for
| | LAN | Tailscale | Cloudflare |
|---|---|---|---|
| reaches | same subnet only | any node in the tailnet, any network | anywhere with internet |
| speed | fastest - a switch hop | good - WireGuard, direct when NAT allows, relayed when not | slowest - leaves the building, crosses a tunnel |
| depends on | nothing but the switch | the Tailscale control plane and the tailnet keys | Cloudflare's edge, the tunnel process, and public DNS |
| fails when | you are off-site, or the switch/VLAN is down | the control plane is down, a key expires, a node is not joined | the tunnel is down, DNS is wrong, or the public route is misconfigured |
| use it for | on-prem boxes: the shop's RDS, the bench, the NAS | server-to-server and management across sites | the public website, customers, any off-tailnet consumer, and as the outer fallback |
## Precedence, per consumer
1. **LAN** if the target is on the same subnet as the caller. Nothing beats a switch hop.
2. **Tailscale** if the target is not on the LAN but is in the tailnet. Private, encrypted, no public
   exposure.
3. **Cloudflare** for anything public, anything not in the tailnet, and as the fallback when both
   private paths fail.
**The selection must be MEASURED, not configured.** Every probe picks the first transport that
actually answers, and reports which one it used and why. A script that hardcodes a transport is the
bug this policy exists to prevent - it turns a working fallback into an untested one.
## Measured state, 2026-10-11 ~20:35Z
- **The cloud authority is on the tailnet**: `secratary-cloud` = `100.73.176.126`, active, direct via
  `178.156.194.1:41641`.
- **But it refuses 8002 over the tailnet** and `443` is open. The app binds `127.0.0.1:8002`, so on
  that box the API has exactly one reachable door, and it is **public**:
  `https://api.abletelsolutions.com/health` -> `200 ok=True db_ok=True` (proved from ZABZ-TECH).
- The old office box correctly **refuses 8002** - it is frozen, read-only, the rollback anchor.
## THE GAP THIS EXPOSES, and it is the point of the policy
**The company's own authority currently has no private path.** Its API is reachable only through the
public internet and a single Cloudflare tunnel. That inverts the intended order: the estate's own
machines should reach it over LAN or Tailscale and fall back to Cloudflare, not depend on Cloudflare
as the only route.
**Recommendation (mine, for the coordinator to execute):** expose the authority on the tailnet - a
private listener the tailnet can reach, with Cloudflare kept as the public door and fallback. Then:
workstations on the office LAN reach it by LAN, off-site machines by Tailscale, and strangers by
Cloudflare. Three paths, ordered, each independently testable.
Note the honest limit of the "LAN is fastest" principle: the authority is in Ashburn, so **LAN cannot
ever apply to it.** LAN applies to on-prem boxes - the shop's operational database, the bench, the
NAS. The policy must not pretend otherwise.
## What the scripts must do
1. Probe each applicable transport with a short timeout and pick the first that answers.
2. Print **which transport was chosen, the evidence, and what the others did** - a silent selection is
   indistinguishable from a bug.
3. Fail loudly when none answers, naming every transport tried and its error. Never fall through to a
   hardcoded default.
4. Be safe to run from any machine, including one that is on neither the LAN nor the tailnet.
5. Carry this policy's precedence, in one place, so a cutover or a new node changes one file.
---
## RESOLVED 2026-10-11 ~20:50Z - the authority now HAS a private path
The gap above is closed, using the mechanism already on the box. Measured, not proposed:
```
tailscale serve --bg --https=8443 http://127.0.0.1:8002      # run on secratary-cloud
```
`tailscale serve status` afterwards:
```
https://secratary-cloud.tail93e6e6.ts.net (tailnet only)
|-- / proxy http://127.0.0.1:3086          <- pre-existing, the DSH web GUI, UNTOUCHED
https://secratary-cloud.tail93e6e6.ts.net:8443 (tailnet only)
|-- / proxy http://127.0.0.1:8002          <- the company authority, added here
```
**Verified from ZABZ-TECH:** `https://secratary-cloud.tail93e6e6.ts.net:8443/health` -> **HTTP 200,
`ok=True`, `db_ok=True`**. The public door still answers 200. `company-api` was **not restarted** -
its `ActiveEnterTimestamp` is unchanged at 2026-10-11 15:17:41Z.
**Honest timings, over 6 SUCCESSFUL calls each:** tailnet avg **0.058s** (min 0.054s) against public
avg **0.067s** (min 0.054s). At this distance the transport is not the bottleneck; the real gain is
that the private path does not depend on Cloudflare, public DNS or the tunnel process.
**Reversible with:** `tailscale serve --https=8443 off`
## Two measurement traps this exercise produced, worth keeping
1. **A fast failure is not a fast path.** An earlier timing run reported "tailnet avg 0.044s" for a
   route that was returning HTTP 000. Failed connections are fast. **Time only successful calls, and
   say how many succeeded.**
2. **`Test-NetConnection` said TCP 443 was open on `100.73.176.126` and it was** - but a request to
   `https://100.73.176.126/health` still fails, because the tailnet listener presents a certificate
   for `secratary-cloud.tail93e6e6.ts.net` and there is no route for a bare tailnet IP with a foreign
   SNI. **Test the name, not the address.**
## What the routing scripts should now implement
| consumer | first | second | third |
|---|---|---|---|
| on the office LAN, reaching on-prem resources | **LAN** | Tailscale | Cloudflare |
| any tailnet machine reaching the authority | **tailnet `:8443`** | public HTTPS | - |
| an off-tailnet or public consumer | **public HTTPS** | - | - |
