# Credentials — where they live and how to reach them

**Written:** 2026-10-05, after losing weeks to a credential that was never actually lost.

## The lesson this file exists to prevent

The Cloudflare token was written to `~/.secrets/cloudflare.env` on **2026-09-18** and verified
working the same day. Yet from then until **2026-10-05** the work queue repeatedly recorded
*"blocked on a credential"* and the owner was asked, twice, for a token he had already provided.

**Nothing was missing. The path to it was missing.** A file that holds a credential is not a
capability — a *documented, scripted, non-interactive path to it* is. A non-interactive shell
(`ssh host "cmd"`, cron, a scheduled shift) does **not** read a login profile, so `source
~/.secrets/cloudflare.env` in a `.bashrc` helps a human and helps automation not at all.

**Rule:** every credential gets (a) one home, (b) one wrapper that reads it, and (c) a line here.
If a future session cannot reach a credential in one command, this file has failed.

## Where they are

| Credential | Home | Notes |
|---|---|---|
| **Cloudflare API token** | `~/.secrets/cloudflare.env` (mode 600) | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_ZONE_ID_LAKEWOODPHONEANDTECH`, `CLOUDFLARE_ZONE_ID_ABLETELSOLUTIONS` |
| Cloudflare token (bare) | `~/.secrets/cloudflare-api-token` | the same token, one value, for tooling that wants a file |
| Twilio (shop line) | `~/.secrets/twilio-lakewood.json` | |
| Dialpad UI headers | `~/.secrets/dialpad-ui-headers.b64` | |
| LPT NJ employer access | `~/.secrets/lpt-nj-employer-access.env` | |
| BitLocker recovery, ZABZ-TECH C: | `~/.secrets/bitlocker-ZABZ-TECH-C.recovery.txt` | |

**Present on:** `secratary` and `ZABZ-YOGA`. If a machine is missing the directory, copy it — do not
re-request the token.

## How to use them — the one command

```bash
scripts/deploy-lpt-frontend.sh --env test            # build + deploy the frontend to TEST
scripts/deploy-lpt-frontend.sh --env test --dry-run  # prove it, change nothing
```

The wrapper sources the credential, **verifies the token against Cloudflare before it builds**
(so a dead token fails in seconds, not after a ten-minute build), and **refuses `--env production`**
outright. Production is a deliberate owner action.

From a machine that has the repo but not the secrets, the same thing over ssh:

```bash
ssh secratary-ts '~/code/harness-config/scripts/deploy-lpt-frontend.sh --env test'
```

## What the credential is, and what it can do

- **Shape:** a Cloudflare **User API token**, 53 characters, prefix `cfut`.
- **Verified** 2026-10-05: `GET /user/tokens/verify` → **200, status active**.
- **Account** `3fe00f424ec43810af16b55df54200a3` sees exactly two Pages projects:
  **`lakewood-phone-test`** and **`lakewood-phone-prod`**.
- The owner queue of 2026-09-16 asked for scopes **Pages:Edit, Zone DNS:Edit, R2:Edit** on the
  `lakewoodphoneandtech.com` zone. **What the token actually carries has not been re-verified** —
  test each scope before relying on it. A `verify` 200 proves the token is alive, not that it can
  edit DNS.

## Creating another one

**The creator is this same token.** Verified 2026-10-05, not assumed:

- `GET /user/tokens/permission_groups` → **200, 413 permission groups visible**. A token scoped to one
  zone's Pages could not list permission groups at all, so this is an **account-level user token**.
- `GET /user/tokens` → **200** — it can read the token collection, which is the permission that mints
  more tokens.
- The account resolves as **"Abletelsolutions@gmail.com's Account"**, id `3fe00f424ec43810af16b55df54200a3`.

So there is **no separate super-token to hunt for**. If a new scoped token is needed, this one can
create it; that is what the owner meant by "the token that creates tokens".

**Do not ask the owner for a token that already exists on two machines.** Check
`~/.secrets/cloudflare.env` first — that mistake cost weeks.

## Machines and reachability

Home and office are separate networks; **Tailscale is the only path between them.** `secratary` is
the authority and the one that runs scheduled work; an agent working there reaches the secret with
a plain `source`, no ssh required.
