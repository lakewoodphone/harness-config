<!-- e:lessons|L1750|2026-09-14|ZABZ-TECH|open -->
**L263 · There is no cheap hidden channel for used iPhones: the floor is 110-125 for working unlocked stock, the levers are grade and lot size, and buying in person wins on risk not price**

## There is no cheap hidden channel for used iPhones, and the search for one is how this system wastes its time

A full sourcing sweep — Asia-direct, the US dealer/ITAD channels, and the trade's own forums — ran on 2026-09-14 to
answer "where do people get genuinely cheap iPhone 11s". The answer is that **the floor for a working, unlocked,
activation-lock-free iPhone 11 64GB is about \-125/unit, and the levers are grade, lot size, returns and depth
of testing — not a supplier nobody has heard of.**

Verified anchors: **\.00/unit is the only visible published dealer ask anywhere** (Cell Dealers, "Used", Tampa,
521 units, page modified 2026-09-14 — opened by me, not reported). Apple's own trade-in pays about **\**. A
120-device lot surfaced in Feb 2026 was **MDM-locked and parts-only**. RecirQ's own guide says the spread between US
suppliers on the *same model and grade* is **\-40/unit**, and that "suppliers offering unusually low prices are
often skipping steps".

**What the trade says when asked directly** (r/Flipping, r/reselling, r/mobilerepair — URLs in the pipeline doc):
- "Someone who has a source for iPhones in bulk has pretty thin margins. They are also not going to share them with you."
- "people usually sell them at a price where you cant resell it and make a profit"
- "Bulk Apple devices are 99.99% either iCloud locked, passcode locked or dead from water damage"
- A dealer who has moved 10,000+ phones sources **"locally from individuals"**, makes \-100 a flip, and says
 **"3rd party activation lock removal is a myth"**.
- The subreddit dedicated to wholesale iPhone lists has **zero comments** on its supplier threads.

**Durable rules:**
1. **Do not re-run this search.** \-125 is the floor for working stock; anything materially cheaper is locked,
 dead, or lying. If a future session is asked to find cheaper iPhones, start from that number and the gate list.
2. **The gates that cannot be passed at 10-50 units:** B-Stock Mobile Carrier (resale cert + **\ screening + ~2
 months**), ITAD companies (enterprise contracts, not dealer lots), and every NJ/NY distributor (call-for-pricing).
 **BidAllies and Vexwire are the same company.** imperialwireless.com and meritel.net are **internet service
 providers** — two names that were wrong in our own earlier research.
3. **Buying in person beats every channel, and not on price — on risk.** Activation lock, carrier lock and IMEI are
 the failure modes that destroy wholesale lots, and at a counter they are **checked before the money moves**. Pay
 \-140 to an individual, verify on the spot, and the dominant risk goes to zero.

---

**L-new · 2026-09-14 · One shared private key, named "mesh", is the credential for production — and it was sitting on the machine a departing employee used.**

**The finding.** `~/.ssh/id_ed25519_hetzner` carries the comment `mesh-hetzner-2026-08-31` and the
fingerprint `SHA256:91iMQc2AFg+sSA1oscDHF9pz7jClBMynfHtRL4rmAKg`. That exact key is the **only** entry in
`/root/.ssh/authorized_keys` on `lpt-apps-01` (Hetzner), which is the host running `lpt-postgres`
(`lpt_prod`), `lpt-backend` and the whole company web stack. The same private key file exists on at least:
`secratary` (the authority), `zabz-tech-linux`, `ZABZ-YOGA`, and `LakewooechsMini` (the mac mini whose own
identity file read `"operator": "yisroel"`).

**Why it matters.** The credential is not per-machine and not attributable: any machine holding it is root
on production, and a copy taken from any one of them opens all of the others. The comment being literally
`"mesh-hetzner"` says this was a deliberate convenience — and it is the same class of problem the journal
already recorded for GitHub (an account-wide token making a second person's commits indistinguishable from
the owner's). **Convenience credentials for a fleet become the fleet's single point of failure.**

**Correction I owe, from checking rather than assuming.** I first reported this as "Yisroel held root on the
production database". That over-states it. On the mac mini the alias `hetzner` resolves to `87.99.141.172`
with `IdentityFile ~/.ssh/id_ed25519_hetzner`, and **`lpt-apps` (2.28.33.58) has no alias on that machine at
all** — so the mac mini's *configured* path used that key for a different host, and its ability to reach
production was latent (the key, not a configured route). The correct statement is: **the key was present on
the machine; the route was not.** Still a serious hygiene failure, because possession is what matters, but
not the active hold it first looked like.

**What I actually did (small, reversible, and recorded):**
1. **Deactivated the departing employee's account** — production `users` id 232, status `ACTIVE` →
 `SUSPENDED`, and **all 24 unrevoked refresh tokens revoked** (0 remain). Identity was confirmed by the
 owner before acting; his employment agreement and hire notes contain no email, so `izyme97@gmail.com`
 was an assumption until he said yes. Backup of the row plus 75 sessions and 55 tokens:
 `/tmp/staff-deactivation-backup/user-232-20260914-224900.json`. **Nothing deleted** — his 98 payments and
 1 assigned order still resolve to his name. Enforcement was *read in the code, not assumed*:
 `auth.service.ts` refuses any non-`ACTIVE` user at login **and** re-checks on refresh-token validation.
2. **Generated a machine-specific key** for the mac mini under its new operator —
 `id_ed25519_yocheved-mac-mini` / `yocheved-mac-mini-2026-09-14` — and updated that machine's identity
 manifest to `operator: yocheved` with `previous_operator: yisroel` (old file backed up beside it).
3. **Retired the shared key from the mac mini only**, moved (not deleted) to `~/.ssh/retired-<date>/`.

**Left deliberately unfinished, and why.** The new key is **not** yet installed on production, and the
shared key is **not** removed from production's `authorized_keys`. Removing it before every machine has its
own key would lock the fleet out of production — the same trap the journal records for the git-identity
problem. **The correct order is: issue a per-machine key everywhere that needs one → install all of them →
verify each opens production → only then delete the shared key.** That is a fleet-wide rotation and it is
the next step, not a half-step.

*Rule:* a credential comment that contains the word **"mesh"** is a warning label. Distribute trust per
machine, not per fleet — and when a person leaves, audit every credential their machine held rather than
the account they logged into.

**L-new2 · 2026-09-14 · `IdentitiesOnly` does not stop ssh from falling back to the config's key — so "authenticated" can mean a key that was never offered.**

**Context.** Rotating a shared production key turned up a verification trap that produced a false PASS and
then a false FAIL, in the same five minutes.

**The trap.** Testing whether the retired shared key still worked, I ran:

 ssh -o BatchMode=yes -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519_hetzner lpt-apps hostname

It returned `lpt-apps-01` with exit 0, and I read that as "the shared key still works — removal failed".
It had not. `ssh -v` showed the real sequence:

 Offering public key: id_ed25519_hetzner -> Authentications that can continue: publickey (REFUSED)
 Offering public key: id_ed25519_lpt-apps -> Server accepts key (ACCEPTED)

The `lpt-apps` **Host block in `~/.ssh/config`** carries its own `IdentityFile`, and OpenSSH tries it after
the `-i` key is refused — `IdentitiesOnly` constrains the agent and the default search, it does not stop a
per-host `IdentityFile` from being used. So a command that looks like it tests key A actually tests "key A,
then key B", and any success indicts neither specifically.

**The fix, and the rule.** Bypass the config entirely when testing a specific key:

 ssh -F none -o IdentitiesOnly=yes -i <key> root@<ip> hostname

With `-F none` the shared key was refused and the per-machine key authenticated — the true state. **When a
test's result decides whether a security control works, test the key in isolation; a per-host config makes
"authenticated" ambiguous between the key you named and the key it fell back to.**

**Sibling failure, same session.** Earlier I "proved" a new key worked with
`ssh ... lpt-apps "echo REACHED $(hostname) as $(whoami)"`. PowerShell expanded `$(hostname)` **locally**
before sending, so the command echoed a literal string and the output looked like success. **Never embed
`$(...)` inside a double-quoted ssh command from PowerShell** — the local shell eats it. Both of these are
the same class: a command that reports success without having tested the thing it names.

**Also worth keeping:** the rotation itself went correctly because it was done in dependency order —
generate → install → *prove each machine* → only then remove the old key — with a rollback copy at each
destructive step. The near-miss came from verification, not from the change.

**L-new3 · 2026-09-14 · `timeout` does not exist on macOS — and every "FAILED" was my harness, not the system.**

**What happened.** After switching a machine's git remotes to a scoped deploy key, my verification ran
`timeout 40 git ls-remote ...` on macOS. There is **no `timeout` binary on macOS** (it is GNU coreutils;
macOS has `gtimeout` only with brew). The shell reported `timeout: command not found`, `git` never ran, and my
`&& echo OK || echo FAILED` reported **FAILED**. I read that as "the deploy key does not work" and came within
one step of reverting a change that was correct.

**Why it looked like a real regression.** Two independent repos failed the same way — including `lpt-hub`,
which I had not touched — which briefly suggested something systemic rather than my own test. The giveaway
was that the same key authenticated fine over `ssh -T`, which is the check I should have trusted.

**The rule.** A test harness that silently cannot execute the thing it tests will report failure, and
**failure is the one result that looks like a real finding.** So: when a check fails, print the underlying
error BEFORE concluding anything. My scripts were swallowing stderr into `>/dev/null` precisely where the
message `timeout: command not found` was waiting, visible the moment I stopped suppressing it.

**Concretely, for this fleet:** use `gtimeout` on macOS or drop the wrapper entirely; and never write
`cmd >/dev/null 2>&1 && OK || FAILED` in a diagnostic — redirect only the *success* case, or capture output
and print it. This is the third harness-induced false result of the session, after the empty `chats.db`
(which had in fact been rebuilt) and the `zstandard.decompress()` single-frame read (which reported "0 of 227
sessions"). **All three were my instrument, not the measurement — and two of the three produced false
NEGATIVES on work that was fine.**

**What the work actually produced (verified after fixing the harness):** a read-only deploy key for the
company repo on the new manager's machine — the repo fetches and a push is **refused**, which is the scoping
the journal specified (`read-only to the company repo, read/write to lpt-hub only`) — and `lpt-hub` still
works through its own scoped deploy key. The departing employee's account-wide key (`id_ed25519_github`,
which authenticated as the **organisation account**, not as him) is retired from that machine.

<!-- j2 tags=legacy-import refs= alias_of= legacy_id=L263 sha=b6c7c9e22f3e7cbc -->
