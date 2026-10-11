# INCIDENT — the authority refused every workstream's SSH key at 06:40Z, 2026-10-11

**Filed by:** the guards/backup port workstream (ZABZ-YOGA), ~07:30Z.
**Severity:** the estate's only interactive way into the company authority was lost. The company
itself kept running (both public doors answered HTTP 200 throughout).

## What happened

| time (UTC) | event |
|---|---|
| 06:26 – 06:39 | I am working on `secratary-cloud` normally: `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1`, four separate sessions, all successful |
| 06:39 | `tar -cf - -C <local> . \| ssh … 'tar -xf - -C / && chmod …'` completes; `ls -la /usr/local/bin/` lists my nine files |
| 06:39:xx | the same listing shows **other** workstreams' deployments with mtimes 06:34–06:37 (`estate-monitor.py`, `lpt-hub-refresh.sh`, `run-company-outcome-monitor.sh`) |
| 06:40 | first refusal |
| 06:41:29 | sibling session reports the same: *"Lost ssh access to the cloud box mid-run (`Permission denied (publickey)`) — the API is still 200."* |
| 06:34 (reported) | sibling session `a38c2c31`: *"I lost ssh to the cloud box at 06:34Z and could not regain it."* |
| 06:48:04 | sibling session `15de3514`: *"My key is still offered but now rejected — `/root/.ssh/authorized_keys` on the authority changed ~20 minutes into my session."* |

**Every porting workstream on this laptop lost the authority between 06:34Z and 06:41Z.**

## What it is NOT

| hypothesis | measurement that kills it |
|---|---|
| the box is down | `https://api.abletelsolutions.com/health` → **HTTP 200** and `https://ai.abletelsolutions.com/` → **HTTP 200** throughout |
| a per-source (fail2ban-style) block on this laptop's IP | the same attempt relayed through `2.28.33.58` (`ssh … root@2.28.33.58 nc 178.156.194.1 22`) is refused identically — **a different source IP** |
| the wrong key | `ssh-keygen -lf id_ed25519_hetzner.pub` → `SHA256:91iMQc2AFg+sSA1oscDHF9pz7jClBMynfHtRL4rmAKg mesh-hetzner-2026-08-31`, which is the single key `135-PARITY-AND-ROBUSTNESS.md` §4.6 records in the box's `authorized_keys`, and which authenticated successfully minutes earlier |
| my own deployment broke it | the archive I sent contained exactly nine files, listed locally: `./root/hc-main.bundle` and `./usr/local/bin/{cron-wrap.sh,cron-target-guard.py,cron-script-guard.py,db-integrity-check.py,prune-backups.sh,tmpfs-reaper.sh,report-offsite-age.sh,guard-registry-check.py}`. **No path in it is under `/etc` or `/root/.ssh`.** |
| a rate limit | it is not clearing: attempts at 06:41, 06:44, 06:47, 06:53, 06:56, 07:00, 07:04 all refuse in < 1 s |

## What the box looked like before the loss (my own reads)

```
root@secratary-cloud: ls -la /root/.ssh/
  -rw------- 1 root root 105 Oct  9 18:23 authorized_keys
  -rw------- 1 root root 411 Oct 11 00:27 id_ed25519
  -rw-r--r-- 1 root root  97 Oct 11 00:27 id_ed25519.pub
  -rw------- 1 root root 419 Oct 11 06:19 id_ed25519_hetzner
  -rw------- 1 root root 1258 Oct 11 06:26 config
```

105 bytes is **one** key. Nothing else can get in.

## Recovery (one of these)

1. **Hetzner console** → `secratary-cloud` (Ashburn, CCX13) → rescue/reset root password → append to
   `/root/.ssh/authorized_keys` (mode 600, owner root):
   ```
   ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHS/d3PK5rIZqVN+/NARxQeWBxkjlvzauXzcZkAHY4Je mesh-hetzner-2026-08-31
   ```
2. **Any session still holding an open channel** (session `15de3514` reported one at 06:48Z — "my
   only live channel is the existing background ssh"): append the same line.
3. **Do not delete `/root/.ssh/id_ed25519`** (the box's own private key; public half
   `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHbUh0wWHB3hUlXiSja8xlAck+OvttWG7xAKa/0pN7hT`). The
   transcript-archive pull and the tailnet repair depend on it.

Nothing in this estate can do any of the three from outside. That is the finding.

## What should exist so this cannot recur

1. **A second authorized key on the authority**, held on a different machine (office box, VPS or
   desktop). The estate's own doc predicted the shape: *"SSH is by public IP and key only and the key
   exists on one machine … Loss of that laptop is loss of the authority"* — and did not imagine the
   key being **replaced on the box** rather than lost on the laptop.
2. **A guard on `authorized_keys` itself**, as a `cron-target-guard` critical path: mode, owner,
   size and a fingerprint comparison. The file that is the single point of entry had no check.
3. **A rule that a deployment touching `/root/.ssh/` is announced and serialised.** Nine sessions
   were writing `/usr/local/bin` in the same five minutes.

## Corroboration, with provenance

* my session `6fd6e9c6-f54e-4a46-84a9-07d2fb0eec11` (ZABZ-YOGA, local)
* `fb30380e-3145-4e41-bc93-73127a62fda9` — 06:43:35Z refusal, and 06:26:28Z successful read of `/usr/local/bin`
* `a38c2c31-60c0-4169-a1a7-ccae89cc4682` — loses it 06:34Z, reports at 06:48:40Z
* `15de3514-c82b-4ff3-9432-761d1768c39a` — 06:48:04Z, and the diagnosis "authorized_keys changed ~20 min into my session"
* `ee49b6bd-92d9-4046-9cf7-26f27eecf391` — 06:41:37Z "authentication is now refused"
* `65c89e10-a99b-4df7-ae33-185c04af8ed6` — 06:42:18Z "Key is proven present in the box's `authorized_keys`"
* `20f613bd-c09d-4487-acea-7f0090d7be3d` — the config/docs context, and `authorized_keys` at 09:18:23 on 9 Oct
* `135-PARITY-AND-ROBUSTNESS.md` §4.6 (the single-key measurement) and §4.7 (the quoted doctrine)
