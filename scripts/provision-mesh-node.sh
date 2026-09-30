#!/usr/bin/env bash
# provision-mesh-node.sh — make a Linux host a real mesh node: runtime, DSH, gate, engine, serve.
#
# Owner: stream S2 of the mesh program (docs/mesh/71-mesh-program.md §3).
# Doc:   docs/mesh/73-linux-pc-node.md
# Reads: docs/mesh/62-worker-runtime.md §1.1/§1.2/§3.4 — the measured recipe this file executes.
#
# THIS SCRIPT DOES NOT EDIT scripts/phone-gate.py. It copies it verbatim; S1 owns that file.
#
# Two halves in one file, because the node keeps a re-runnable copy of exactly what provisioned it:
#
#   local half   (default)    push the gate + this script to the node, then invoke the remote half
#   remote half  (--remote)   everything that must happen ON the node. Idempotent and re-runnable.
#
# The trap this script exists to avoid (docs/mesh/62-worker-runtime.md §1.1):
#   `@deepseek-ai/dsh/lib/bin.js:168` is `if (import.meta.main)`. On a Node older than 22.18 the
#   process exits 0 having done NOTHING — no output, no listener, no error. Ubuntu 24.04's own
#   `apt install nodejs` is 18.19.1 and is exactly that trap. We therefore take a nodejs.org
#   tarball under $HOME/.local, pinned to the version the authority itself runs, and install DSH
#   with `npm ci` from the authority's package-lock.json so the version is pinned, not ranged.
#
# Exit codes (a caller can branch on these; nothing else is returned):
#   0   provisioned, and the headless turn returned the expected string
#   2   preflight refused (no ssh / bad arch / not enough space to install at all)
#   3   a step failed (download, checksum, npm ci, env file, unit)
#   4   provisioned but verification failed (gate / engine / the headless turn)
#   20  REFUSED to establish a fleet worktree root: <20 GiB free on that filesystem
#
# Everything written on the node, and nothing else:
#   $HOME/.local/node-<ver>-linux-<arch>/   the interpreter (tarball, verified against SHASUMS256)
#   $HOME/.local/node                      stable symlink -> the interpreter directory
#   $HOME/dsh-engine/                      DSH install (package.json + package-lock.json from the
#                                          authority, then `npm ci --omit=dev`)
#   $HOME/dsh-mesh/repo/                   deploy tree: scripts/phone-gate.py + assets/, and a copy
#                                          of this script (no profile is edited; see step 6b for why
#                                          dsh-plugin-health is NOT mounted here by default)
#   $HOME/.dsh-phone/                      engine + gate logs (the gate finds the launch token there)
#   $HOME/.dsh-mesh/                       mesh state: provisioned.json, workroot.json, logs
#   /etc/dsh-worker.env                    0640 root:<user> — the model credentials
#   /usr/local/bin/dsh                     launcher; resolves the interpreter, never names a version
#   /usr/local/bin/{node,npm,npx,corepack} symlinks, so a bare `node --version` works over ssh
#   /etc/systemd/system/dsh-engine.service
#   /etc/systemd/system/phone-gate.service
#   tailscale serve: https 443 -> http://127.0.0.1:<gate-port>
#
# It writes nothing into the harness-config checkout on the node. That checkout has diverged and a
# pull would fail, so every file it needs is pushed, never merged (71 §3's rule for this stream).

set -euo pipefail

self="${BASH_SOURCE[0]:-$0}"
prog="${self##*/}"

# --------------------------------------------------------------------------- defaults
remote=0
check_only=0
host=linux-pc-ts
authority=secratary                 # ssh target, reached FROM the node (it is on the office LAN)
authority_dsh_dir=dsh-engine        # relative to the authority user's home
node_version=""                     # empty -> ask the authority, else fall back
fallback_node_version=v22.23.2
engine_port=3099
gate_port=3086
fqdn=""
deploy_root=""
dsh_dir=""
env_file=/etc/dsh-worker.env
work_root=""
min_work_free_gib=20
force=0
skip_serve=0
do_reclaim=0
with_health_plugin=0
assert_work_root=0
expect_reply="NODE OK"
ssh_opts=(-o BatchMode=yes -o ConnectTimeout=8)
fwd=()                              # args forwarded to the remote half

usage() {
  cat <<USAGE
$prog — provision a Linux mesh node (runtime + DSH + gate + engine + serve).

  $prog [-H host] [options]              provision (default host: linux-pc-ts)
  $prog -H host --assert-work-root       read-only: does this node's filesystem accept a fleet
                                         worktree root? exit 0 accept / 20 refuse
  $prog -H host --check                  report the node's facts, install nothing

Options
  -H, --host HOST          ssh target (alias from ~/.ssh/config, or user@ip)   [$host]
  --authority TARGET       ssh target holding package-lock.json + credentials  [$authority]
  --node-version V         pin the runtime, e.g. v22.23.2 (default: the authority's own version)
  --engine-port N          engine port, loopback only                          [$engine_port]
  --gate-port N            gate port, the one tailscale serve publishes         [$gate_port]
  --fqdn NAME              tailnet FQDN for --trusted-host (default: read from the node)
  --deploy-root PATH       where the gate + this script are deployed  [\$HOME/dsh-mesh/repo]
  --dsh-dir PATH           where DSH is installed                          [\$HOME/dsh-engine]
  --env-file PATH          credentials file (root-owned)               [/etc/dsh-worker.env]
  --work-root PATH         the fleet worktree root to authorise        [\$HOME/code/_worktrees]
  --min-work-free-gib N    refuse a fleet worktree root below this      [$min_work_free_gib]
  --reclaim                opt in to 'journalctl --vacuum-size=500M' + 'apt-get clean'
  --with-health-plugin     mount dsh-plugin-health into the web profile. OFF by default and it is
                           NOT recommended on a non-Windows node: its process probe is Windows-only
                           (lib/snapshot.ps1 P/Invokes kernel32), so /healthz answers a permanent 503
                           and it makes the gate advertise fleet capacity nothing governs. See 6b.
  --skip-serve             do not publish with 'tailscale serve'
  --force                  reinstall the runtime / DSH / env file even when already present
  --expect-reply TEXT      the string the verification turn must return   [$expect_reply]
  -h, --help
USAGE
}

die()  { printf '%s: %s\n' "$prog" "$*" >&2; exit "${EXIT_CODE:-3}"; }
say()  { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }
warn() { printf '   !! %s\n' "$*" >&2; }
run()  { printf '+'; printf ' %q' "$@"; printf '\n'; "$@"; }

# File transfer is `ssh + cat`, never scp. scp is the one command in this script that is NOT
# portable: under MSYS a `C:/...` source path makes it die with "Connection closed", and it needs
# the remote sftp subsystem. A pipe needs neither.
push_file() {  # <local> <remote-target> <remote-dest>
  local src="$1" tgt="$2" dest="$3"
  printf '+ ssh %s "cat > %s" < %s\n' "$tgt" "$dest" "$src"
  ssh "${ssh_opts[@]}" "$tgt" "cat > '$dest'" < "$src"
}
pull_file() {  # <remote-source> <remote-path> <local-dest>
  local tgt="$1" path="$2" dest="$3"
  printf '+ ssh %s "cat %s" > %s\n' "$tgt" "$path" "$dest"
  ssh "${ssh_opts[@]}" "$tgt" "cat '$path'" > "$dest"
}
push_tree() {  # <local-dir> <remote-target> <remote-dir>
  local src="$1" tgt="$2" dest="$3"
  printf '+ tar -c -C %s . | ssh %s "mkdir -p %s && tar -x -C %s"\n' "$src" "$tgt" "$dest" "$dest"
  tar -c -C "$src" . | ssh "${ssh_opts[@]}" "$tgt" "mkdir -p '$dest' && tar -x -C '$dest'"
}

# --------------------------------------------------------------------------- args
parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --remote)            remote=1 ;;
      -H|--host)           host="$2"; fwd+=(--host "$2"); shift ;;
      --authority)         authority="$2"; fwd+=(--authority "$2"); shift ;;
      --node-version)      node_version="$2"; fwd+=(--node-version "$2"); shift ;;
      --engine-port)       engine_port="$2"; fwd+=(--engine-port "$2"); shift ;;
      --gate-port)         gate_port="$2"; fwd+=(--gate-port "$2"); shift ;;
      --fqdn)              fqdn="$2"; fwd+=(--fqdn "$2"); shift ;;
      --deploy-root)       deploy_root="$2"; fwd+=(--deploy-root "$2"); shift ;;
      --dsh-dir)           dsh_dir="$2"; fwd+=(--dsh-dir "$2"); shift ;;
      --env-file)          env_file="$2"; fwd+=(--env-file "$2"); shift ;;
      --work-root)         work_root="$2"; fwd+=(--work-root "$2"); shift ;;
      --min-work-free-gib) min_work_free_gib="$2"; fwd+=(--min-work-free-gib "$2"); shift ;;
      --expect-reply)      expect_reply="$2"; fwd+=(--expect-reply "$2"); shift ;;
      --reclaim)           do_reclaim=1; fwd+=(--reclaim) ;;
      --with-health-plugin) with_health_plugin=1; fwd+=(--with-health-plugin) ;;
      --skip-serve)        skip_serve=1; fwd+=(--skip-serve) ;;
      --force)             force=1; fwd+=(--force) ;;
      --assert-work-root)  assert_work_root=1 ;;
      --check)             check_only=1 ;;
      -h|--help)           usage; exit 0 ;;
      *)                   die "unknown argument: $1 (try --help)" ;;
    esac
    shift
  done
}
parse_args "$@"

# ============================================================================ LOCAL HALF
local_half() {
  say "preflight — can we reach $host?"
  ssh "${ssh_opts[@]}" "$host" true || die "ssh $host failed"
  local facts remote_home
  facts="$(ssh "${ssh_opts[@]}" "$host" 'hostname; uname -m; id -un; printf %s "$HOME"')"
  note "node: $(printf '%s' "$facts" | tr '\n' ' ')"
  remote_home="$(printf '%s\n' "$facts" | sed -n 4p)"
  : "${remote_home:?could not read \$HOME on $host}"
  deploy_root="${deploy_root:-$remote_home/dsh-mesh/repo}"
  work_root="${work_root:-$remote_home/code/_worktrees}"
  dsh_dir="${dsh_dir:-$remote_home/dsh-engine}"
  fwd+=(--deploy-root "$deploy_root" --dsh-dir "$dsh_dir" --work-root "$work_root")

  if [ "$assert_work_root" = 1 ]; then
    assert_work_root_here "$remote_home"
    return
  fi
  if [ "$check_only" = 1 ]; then
    check_here
    return
  fi

  say "deploying the gate + this script to $deploy_root"
  ssh "${ssh_opts[@]}" "$host" "mkdir -p '$deploy_root/scripts' '$deploy_root/assets' '$remote_home/.dsh-mesh'"
  local repo
  repo="$(cd "$(dirname "$self")/.." && pwd)"
  [ -f "$repo/scripts/phone-gate.py" ] || die "no $repo/scripts/phone-gate.py to deploy"
  push_file "$repo/scripts/phone-gate.py" "$host" "$deploy_root/scripts/phone-gate.py"
  local a
  for a in mobile.css question-card.css phone-badge.js; do
    push_file "$repo/assets/$a" "$host" "$deploy_root/assets/$a"
  done
  push_file "$self" "$host" "$deploy_root/provision-mesh-node.sh"
  note "gate source: $repo/scripts/phone-gate.py (S1 owns it; copied verbatim, never edited)"
  # plugin-health is the engine's /healthz surface, and mesh-health.ps1's verdict for this node is
  # decided by that route — but mounting it here MEASURED WORSE than not mounting it, so it is
  # opt-in only. Do not "fix" this by turning it on: read step 6b first.
  if [ "$with_health_plugin" = 1 ] && [ -d "$repo/packages/plugin-health/lib" ]; then
    push_tree "$repo/packages/plugin-health" "$host" "$deploy_root/packages/plugin-health"
  fi

  say "running the remote half on $host"
  local quoted
  printf -v quoted '%q ' "${fwd[@]}"
  printf '+ ssh %s bash %s/provision-mesh-node.sh --remote %s\n' "$host" "$deploy_root" "$quoted"
  ssh "${ssh_opts[@]}" "$host" "bash '$deploy_root/provision-mesh-node.sh' --remote $quoted"
}

# Read-only. Four lines of arithmetic, deliberately duplicated so this works on a node that has
# never been provisioned; keep in step with the block in the remote half.
assert_work_root_here() {
  local rhome="$1" wr avail_kib avail_gib
  wr="${work_root:-$rhome/code/_worktrees}"
  avail_kib="$(ssh "${ssh_opts[@]}" "$host" "df -Pk '$wr' 2>/dev/null | awk 'NR==2{print \$4}'")"
  : "${avail_kib:?could not read free space for $wr}"
  avail_gib=$(( avail_kib / 1024 / 1024 ))
  if [ "$avail_gib" -ge "$min_work_free_gib" ]; then
    printf 'ACCEPT %s: %s GiB free (>= %s)\n' "$wr" "$avail_gib" "$min_work_free_gib"
    return 0
  fi
  printf 'REFUSE %s: %s GiB free (< %s) — not enough for a fleet worktree root\n' \
         "$wr" "$avail_gib" "$min_work_free_gib" >&2
  return 20
}

check_here() {
  say "facts — nothing is installed by --check"
  ssh "${ssh_opts[@]}" "$host" "
    echo '--- identity ---'; hostname; uname -a; id
    echo '--- disk ---'; df -Pk \"\$HOME\"; df -Ph / /home 2>/dev/null
    echo '--- memory ---'; free -m
    echo '--- runtime ---'; command -v node || echo 'node: NOT ON PATH'
    ls -d \"\$HOME\"/.local/node* 2>/dev/null || echo '~/.local/node*: absent'
    echo '--- dsh ---'; ls -d \"\$HOME\"/dsh-engine 2>/dev/null || echo '~/dsh-engine: absent'
    ls -d \"\$HOME\"/.dsh 2>/dev/null || echo '~/.dsh: absent'
    echo '--- apt nodejs (must NOT be used) ---'; apt-cache policy nodejs 2>/dev/null | sed -n 2p
    echo '--- tailscale ---'; tailscale status --json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"Self\"][\"DNSName\"])'; tailscale serve status
    echo '--- listeners ---'; ss -tlnH | awk '{print \$4}'
    echo '--- units ---'; systemctl is-active dsh-engine.service phone-gate.service 2>&1
    echo '--- authority ---'; ssh ${ssh_opts[*]} $authority 'hostname; \"\$HOME\"/node/bin/node -v' 2>&1 | head -3
    echo '--- work root ---'; df -Pk \"\$HOME/code/_worktrees\" 2>/dev/null | awk 'NR==2{printf \"%s: %d GiB free\n\", \$6, \$4/1024/1024}'
  "
}

# =========================================================================== REMOTE HALF
remote_half() {
  : "${HOME:?HOME must be set — that is the recipe, docs/mesh/62-worker-runtime.md §1.4}"

  local user group host_name arch tarball_arch
  user="$(id -un)"
  group="$(id -gn)"
  host_name="$(hostname)"
  arch="$(uname -m)"
  case "$arch" in
    x86_64|amd64)   tarball_arch=x64 ;;
    aarch64|arm64)  tarball_arch=arm64 ;;
    *) die "unsupported architecture: $arch" ;;
  esac

  deploy_root="${deploy_root:-$HOME/dsh-mesh/repo}"
  dsh_dir="${dsh_dir:-$HOME/dsh-engine}"
  work_root="${work_root:-$HOME/code/_worktrees}"
  STATE_DIR="$HOME/.dsh-mesh"
  LOG_DIR="$HOME/.dsh-phone"
  mkdir -p "$STATE_DIR" "$LOG_DIR" "$HOME/code"

  say "S2 provision — $host_name ($arch), user $user, $(date -u +%FT%TZ)"
  note "log: $LOG"

  local rc=0
  local -a failures=()

  # ---------------------------------------------------------------- 1. facts + disk
  say "1. facts"
  run uname -a
  run df -Pk "$HOME"
  run free -m
  local avail_kib avail_gib
  avail_kib="$(df -Pk "$HOME" | awk 'NR==2{print $4}')"
  avail_gib=$(( avail_kib / 1024 / 1024 ))
  note "free on the filesystem holding \$HOME: ${avail_gib} GiB"
  if [ "$avail_gib" -lt 2 ]; then
    EXIT_CODE=2 die "under 2 GiB free — not enough to install the runtime (~250 MiB) at all"
  fi
  if [ "$check_only" = 1 ]; then
    note "--check: stopping here, nothing installed."
    return 0
  fi

  if [ "$do_reclaim" = 1 ]; then
    say "1b. reclaim (--reclaim)"
    run sudo -n journalctl --vacuum-size=500M || warn "journal vacuum failed"
    run sudo -n apt-get clean || warn "apt-get clean failed"
    run df -Pk "$HOME"
    avail_kib="$(df -Pk "$HOME" | awk 'NR==2{print $4}')"
    avail_gib=$(( avail_kib / 1024 / 1024 ))
    note "free after reclaim: ${avail_gib} GiB"
  else
    # `|| true` on both: du exits 1 on a root-only directory while still printing the size it
    # could read, and errexit would otherwise abort the whole run over a cosmetic figure.
    local jsize aptsize
    jsize="$(journalctl --disk-usage 2>/dev/null | grep -oE '[0-9.]+[KMG]' | tail -1 || true)"
    aptsize="$(du -sh /var/cache/apt 2>/dev/null | cut -f1 || true)"
    note "reclaim available but NOT requested (--reclaim): journald ${jsize:-?}, apt cache ${aptsize:-?}"
  fi

  # ---------------------------------------------- 2. the interpreter (pinned, verified)
  say "2. node runtime"
  if [ -z "$node_version" ]; then
    if ssh "${ssh_opts[@]}" "$authority" 'test -x "$HOME"/node/bin/node' >/dev/null 2>&1; then
      node_version="$(ssh "${ssh_opts[@]}" "$authority" '"$HOME"/node/bin/node -v')"
      note "pinned to the authority's own version: $node_version"
    else
      node_version="$fallback_node_version"
      warn "could not read node -v from $authority; falling back to $node_version"
    fi
  fi
  # The floor is NOT arbitrary: below 22.18 `import.meta.main` is undefined and bin.js exits 0
  # having done nothing (docs/mesh/62-worker-runtime.md §1.1).
  local major minor
  major="${node_version#v}"; major="${major%%.*}"
  minor="${node_version#v*.}"; minor="${minor%%.*}"
  if [ "$major" -lt 22 ] || { [ "$major" -eq 22 ] && [ "$minor" -lt 18 ]; }; then
    die "$node_version is below the 22.18 floor — bin.js would exit 0 having done nothing"
  fi
  note "$node_version is >= 22.18, so import.meta.main exists"

  local node_dir="$HOME/.local/node-$node_version-linux-$tarball_arch"
  local node_link="$HOME/.local/node"
  if [ -x "$node_dir/bin/node" ] && [ "$("$node_dir/bin/node" -v 2>/dev/null)" = "$node_version" ] && [ "$force" != 1 ]; then
    note "already installed and self-consistent: $node_dir ($("$node_dir/bin/node" -v))"
  else
    if [ -e "$node_dir" ] && [ "$force" != 1 ]; then
      die "$node_dir exists but does not report $node_version; inspect it, or re-run with --force"
    fi
    if [ -e "$node_dir" ] && [ "$force" = 1 ]; then
      # --force is the explicit per-action yes for this removal. The path is pattern-checked
      # first: it is the runtime directory this script owns and nothing else lives there.
      case "$node_dir" in
        "$HOME"/.local/node-v*-linux-*) note "--force: replacing $node_dir" ;;
        *) die "refusing to remove an unexpected path: $node_dir" ;;
      esac
      run rm -rf "$node_dir"
    fi
    mkdir -p "$HOME/.local"
    local tarball="node-$node_version-linux-$tarball_arch.tar.xz"
    local base="https://nodejs.org/dist/$node_version"
    run curl -fsSL -o "$HOME/.local/$tarball" "$base/$tarball"
    run curl -fsSL -o "$HOME/.local/SHASUMS256.txt" "$base/SHASUMS256.txt"
    local want got
    want="$(awk -v f="$tarball" '$2==f{print $1}' "$HOME/.local/SHASUMS256.txt")"
    [ -n "$want" ] || die "no checksum for $tarball in SHASUMS256.txt"
    got="$(sha256sum "$HOME/.local/$tarball" | cut -d' ' -f1)"
    if [ "$want" != "$got" ]; then
      rm -f "$HOME/.local/$tarball"
      die "sha256 mismatch for $tarball: want $want got $got"
    fi
    note "sha256 verified: $got"
    run tar -xJf "$HOME/.local/$tarball" -C "$HOME/.local"
    [ -x "$node_dir/bin/node" ] || die "extraction did not produce $node_dir/bin/node"
    run rm -f "$HOME/.local/$tarball" "$HOME/.local/SHASUMS256.txt"
  fi
  # A stable path so no caller ever names a version (the mac-mini launcher's measured failure, 62 §3.2).
  run ln -sfn "$node_dir" "$node_link"
  local node="$node_link/bin/node"
  run "$node" -v
  [ "$("$node" -v)" = "$node_version" ] || die "$node -v is not $node_version"
  note "stable interpreter path: $node_link/bin/node"

  # ------------------------------------------------------- 3. DSH, pinned by lockfile
  say "3. DSH install (npm ci from the authority's package-lock.json — pinned, not ranged)"
  mkdir -p "$dsh_dir"
  local incoming="$dsh_dir/.incoming"
  mkdir -p "$incoming"
  pull_file "$authority" "$authority_dsh_dir/package.json"      "$incoming/package.json"
  pull_file "$authority" "$authority_dsh_dir/package-lock.json" "$incoming/package-lock.json"
  [ -s "$incoming/package-lock.json" ] || die "no lockfile came back from $authority"
  local lock_version lock_sha
  lock_version="$("$node" -p "require('$incoming/package-lock.json').packages['node_modules/@deepseek-ai/dsh'].version")"
  lock_sha="$(sha256sum "$incoming/package-lock.json" | cut -d' ' -f1)"
  note "@deepseek-ai/dsh pinned by the lock to $lock_version (lock sha256 ${lock_sha:0:16}…)"
  local installed_version=""
  if [ -f "$dsh_dir/node_modules/@deepseek-ai/dsh/package.json" ]; then
    installed_version="$("$node" -p "require('$dsh_dir/node_modules/@deepseek-ai/dsh/package.json').version")"
  fi
  local need_ci=1
  if [ "$installed_version" = "$lock_version" ] && [ "$force" != 1 ]; then
    need_ci=0
    note "already installed: @deepseek-ai/dsh $installed_version — skipping npm ci"
  fi
  run cp -f "$incoming/package.json" "$dsh_dir/package.json"
  run cp -f "$incoming/package-lock.json" "$dsh_dir/package-lock.json"
  if [ "$need_ci" = 1 ]; then
    note "npm ci --omit=dev — the slow step (583 packages); watch for the integrity check"
    run env PATH="$node_link/bin:$PATH" "$node_link/bin/npm" --prefix "$dsh_dir" ci --omit=dev --no-audit --no-fund
  fi
  local dsh_bin="$dsh_dir/node_modules/@deepseek-ai/dsh/lib/bin.js"
  [ -f "$dsh_bin" ] || die "no $dsh_bin after install"
  # --version, not a smoke prompt: it proves runCli() was REACHED, which is what import.meta.main
  # gates. On a too-old Node this prints nothing and exits 0, so an empty string is the alarm.
  run "$node" "$dsh_bin" --version
  local dsh_version; dsh_version="$("$node" "$dsh_bin" --version 2>/dev/null | tail -1)"
  note "DSH $dsh_version"
  [ -n "$dsh_version" ] || die "dsh --version printed nothing — the interpreter is too old (see header)"
  local p
  for p in dsh-headless dsh-base dsh-web-app; do
    [ -d "$dsh_dir/node_modules/@deepseek-ai/$p" ] || die "$p missing from the install"
  done
  note "headless + base + web bundles present in the install"

  # ------------------------------------------------------------ 4. credentials (env)
  say "4. credentials -> $env_file (0640 root:$group)"
  local have_env=0 env_rewritten=0
  if sudo -n test -s "$env_file" 2>/dev/null; then have_env=1; fi
  if [ "$have_env" = 1 ] && [ "$force" != 1 ]; then
    note "already present ($(sudo -n stat -c '%a %U %G' "$env_file")) — left untouched (--force to rewrite)"
  else
    local tmp; tmp="$(mktemp "$STATE_DIR/creds-XXXXXX")"
    chmod 600 "$tmp"
    if ! ssh "${ssh_opts[@]}" "$authority" 'cat "$HOME"/.dsh/.credentials.yaml' > "$tmp" 2>/dev/null || [ ! -s "$tmp" ]; then
      rm -f "$tmp"
      EXIT_CODE=3 die "could not read $authority:\$HOME/.dsh/.credentials.yaml for the model key"
    fi
    local envsrc="$STATE_DIR/worker.env.new"
    "$node" -e '
      const fs = require("fs");
      const out = [];
      const lines = fs.readFileSync(process.argv[1], "utf8").split(/\r?\n/);
      let inRefs = false;
      const q = (v) => "\"" + v.replace(/([\\"$`])/g, "\\$1") + "\"";
      for (const line of lines) {
        if (/^refs:\s*$/.test(line)) { inRefs = true; continue; }
        if (!inRefs) continue;
        if (/^\S/.test(line)) { inRefs = false; continue; }
        const m = /^\s+([A-Za-z_][A-Za-z0-9_]*):\s*(.+?)\s*$/.exec(line);
        if (!m) continue;
        let v = m[2];
        if ((v.startsWith("\"") && v.endsWith("\"")) || (v.startsWith("\x27") && v.endsWith("\x27"))) v = v.slice(1, -1);
        if (/\n/.test(v)) throw new Error("newline in credential " + m[1]);
        out.push(m[1] + "=" + q(v));
      }
      if (!out.length) throw new Error("no refs found");
      fs.writeFileSync(process.argv[2], out.join("\n") + "\n", { mode: 0o600 });
      console.log("wrote " + out.length + " credential(s): " + out.map((l) => l.split("=")[0]).join(" "));
    ' "$tmp" "$envsrc"
    run rm -f "$tmp"
    run sudo -n install -m 0640 -o root -g "$group" "$envsrc" "$env_file"
    rm -f "$envsrc"
    env_rewritten=1
    sudo -n test -s "$env_file" || die "the credentials file was not written to $env_file"
    note "wrote $(sudo -n stat -c '%a %U %G' "$env_file"); no value is ever printed"
  fi

  # ------------------------------------------------------------------- 5. launcher
  say "5. launcher /usr/local/bin/dsh"
  local launcher_tmp; launcher_tmp="$(mktemp "$STATE_DIR/dsh-XXXXXX")"
  cat > "$launcher_tmp" <<'LAUNCHER'
#!/bin/sh
# dsh — mesh worker launcher. Installed by scripts/provision-mesh-node.sh (stream S2).
# It RESOLVES the interpreter from $HOME/.local/node (a stable symlink), so nothing here names
# a Node version: docs/mesh/62-worker-runtime.md §3.2 measured what a version-stamped path costs.
set -e
home="${HOME:-$(getent passwd "$(id -un)" | cut -d: -f6)}"
node="$home/.local/node/bin/node"
[ -x "$node" ] || { echo "dsh: no Node runtime at $node — run provision-mesh-node.sh" >&2; exit 2; }
bin="$home/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js"
[ -f "$bin" ] || { echo "dsh: no DSH install at $bin — run provision-mesh-node.sh" >&2; exit 2; }
env_file="${DSH_WORKER_ENV:-/etc/dsh-worker.env}"
if [ -r "$env_file" ]; then
  set -a
  . "$env_file"
  set +a
fi
exec "$node" "$bin" "$@"
LAUNCHER
  if sudo -n test -f /usr/local/bin/dsh && sudo -n cmp -s "$launcher_tmp" /usr/local/bin/dsh; then
    note "unchanged — left in place"
  else
    run sudo -n install -m 0755 -o root -g root "$launcher_tmp" /usr/local/bin/dsh
    note "installed (non-interactive ssh PATH is /usr/bin:/bin:..., so ~/.local/bin would never be found)"
  fi
  rm -f "$launcher_tmp"
  run env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin /usr/local/bin/dsh --version

  # `node` by name. /usr/local/bin is on the non-interactive ssh PATH, so this is what makes
  # `ssh <node> node --version` work at all. It can never be Ubuntu's apt node 18 (the header):
  # nothing on this box installs that, and this symlink is the only `node` on the PATH.
  local b
  for b in node npm npx corepack; do
    [ -e "$node_link/bin/$b" ] || continue
    if [ "$(sudo -n readlink /usr/local/bin/$b 2>/dev/null || true)" = "$node_link/bin/$b" ]; then
      note "/usr/local/bin/$b -> $node_link/bin/$b (unchanged)"
    else
      run sudo -n ln -sfn "$node_link/bin/$b" "/usr/local/bin/$b"
    fi
  done
  run env -i PATH=/usr/local/bin:/usr/bin:/bin node --version
  run env -i PATH=/usr/local/bin:/usr/bin:/bin npm --version

  # --------------------------------------------------------------------- 6. units
  say "6. systemd units"
  if [ -z "$fqdn" ]; then
    fqdn="$(tailscale status --json 2>/dev/null | "$node" -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{try{process.stdout.write(JSON.parse(s).Self.DNSName.replace(/\.$/,""))}catch(e){}})')" || true
  fi
  if [ -z "$fqdn" ]; then
    fqdn="$host_name.tail93e6e6.ts.net"
    warn "could not read the tailnet FQDN; guessed $fqdn — a wrong value here 403s every /api call"
  fi
  note "FQDN: $fqdn"

  local u_engine=/etc/systemd/system/dsh-engine.service
  local u_gate=/etc/systemd/system/phone-gate.service
  local e_tmp g_tmp
  e_tmp="$(mktemp "$STATE_DIR/unit-engine-XXXXXX")"
  g_tmp="$(mktemp "$STATE_DIR/unit-gate-XXXXXX")"
  cat > "$e_tmp" <<EOF
[Unit]
Description=DSH engine, mesh worker $host_name (loopback-only; the fence trusts the tailnet name)
Documentation=file:$deploy_root/scripts/phone-gate.py
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$user
Group=$group
# cwd decides where this node's session directories live (docs/mesh/62-worker-runtime.md §1.5(c)),
# so it is fixed here instead of whatever directory a human happened to be in.
WorkingDirectory=$HOME/code
# systemd does not set HOME. Without it ~/.dsh resolves to / or fails (62 §1.4).
Environment=HOME=$HOME
Environment=DSH_HOME=$HOME/.dsh
Environment=NODE_ENV=production
# The model key lives in the environment, not in ~/.dsh/.credentials.yaml, so an agent running on
# this node cannot rewrite it (docs/mesh/62-worker-runtime.md §1.5(a)).
EnvironmentFile=$env_file
ExecStart=$HOME/.local/node/bin/node $dsh_dir/node_modules/@deepseek-ai/dsh/lib/bin.js web --port $engine_port --no-open --trusted-host $fqdn
Restart=always
RestartSec=3
# The one-time launch token is a line on stdout and the gate scrapes it from this file.
StandardOutput=append:$LOG_DIR/engine-$engine_port.log
StandardError=append:$LOG_DIR/engine-$engine_port.err

[Install]
WantedBy=multi-user.target
EOF
  cat > "$g_tmp" <<EOF
[Unit]
Description=Phone gate for $host_name: signs a cold visitor in, serves /mesh/capacity, relays /api
Documentation=file:$deploy_root/scripts/phone-gate.py
After=dsh-engine.service
Wants=dsh-engine.service

[Service]
Type=simple
User=$user
Group=$group
WorkingDirectory=$deploy_root
Environment=HOME=$HOME
Environment=PHONE_MOBILE_CSS=1
ExecStart=/usr/bin/python3 $deploy_root/scripts/phone-gate.py --listen-port $gate_port --engine-port $engine_port
Restart=always
RestartSec=2
LimitNOFILE=8192
StandardOutput=append:$LOG_DIR/gate.log
StandardError=append:$LOG_DIR/gate.log

[Install]
WantedBy=multi-user.target
EOF

  local units_changed=0 pair unit tmpf
  for pair in "$u_engine:$e_tmp" "$u_gate:$g_tmp"; do
    unit="${pair%%:*}"; tmpf="${pair##*:}"
    if sudo -n test -f "$unit" && sudo -n cmp -s "$tmpf" "$unit"; then
      note "$unit unchanged"
    else
      run sudo -n install -m 0644 -o root -g root "$tmpf" "$unit"
      units_changed=1
    fi
  done
  rm -f "$e_tmp" "$g_tmp"
  if [ "$units_changed" = 1 ]; then run sudo -n systemctl daemon-reload; fi
  run sudo -n systemctl enable dsh-engine.service phone-gate.service

  # Restart only what must restart, and this is THIS node's engine only — no other machine is touched.
  # (if/then, not `cmd && var=1`: under errexit a false condition in an && list is a fatal status.)
  local engine_was_active=0 gate_was_active=0
  if systemctl is-active --quiet dsh-engine.service; then engine_was_active=1; fi
  if systemctl is-active --quiet phone-gate.service; then gate_was_active=1; fi

  if [ "$units_changed" = 1 ] || [ "$engine_was_active" = 0 ] || [ "$env_rewritten" = 1 ]; then
    run sudo -n systemctl restart dsh-engine.service
  else
    note "dsh-engine.service already running with this unit — not restarted"
  fi

  # The gate must be restarted when its own file changed (that is how a new S1 route lands) or
  # when it is not running. Otherwise a healthy gate is left alone.
  local gate_sha gate_stamp="$STATE_DIR/gate.sha256" gate_changed=1
  gate_sha="$(sha256sum "$deploy_root/scripts/phone-gate.py" | cut -d' ' -f1)"
  if [ -f "$gate_stamp" ] && [ "$(cat "$gate_stamp")" = "$gate_sha" ]; then gate_changed=0; fi
  note "phone-gate.py sha256 ${gate_sha:0:16}… ($([ "$gate_changed" = 1 ] && echo changed || echo unchanged))"
  if [ "$gate_changed" = 1 ] || [ "$gate_was_active" = 0 ] || [ "$units_changed" = 1 ]; then
    run sudo -n systemctl restart phone-gate.service
  else
    note "phone-gate.service already running this exact file — not restarted"
  fi
  printf '%s\n' "$gate_sha" > "$gate_stamp"
  sleep 2
  local svc
  for svc in dsh-engine.service phone-gate.service; do
    if systemctl is-active --quiet "$svc"; then
      note "$svc active"
    else
      failures+=("$svc is not active after restart")
      rc=4
      run sudo -n journalctl -u "$svc" --no-pager --lines=25 || true
    fi
  done

  # ------------------------------- 6b. /healthz — plugin-health, OFF by default, and why
  # Mounting dsh-plugin-health on this node MEASURED WORSE THAN NOT MOUNTING IT, 2026-09-16
  # 23:19-23:22Z. Three independent reasons, all of them in the repo rather than in this script:
  #
  #  1. Its process probe is Windows-only BY CONSTRUCTION. lib/snapshot.ps1 P/Invokes kernel32
  #     CreateToolhelp32Snapshot and says so in its own header ("Windows has no /proc"), and
  #     lib/index.js:793 answers `processes.available && !processes.stale ? 200 : 503`. On a Linux
  #     node `available` is false forever, so /healthz is a PERMANENT 503, not a degraded 200.
  #  2. scripts/mesh-health.ps1:130-134 maps 404 -> WARN and ANYTHING ELSE -> FAIL. So mounting it
  #     turns this node's line from the WARN that secratary also carries into a hard FAIL.
  #     MEASURED with it mounted: "FAIL: GET /healthz (with the cookie from GET /) -> 503".
  #  3. Mounting it creates $DSH_HOME/governor, and scripts/phone-gate.py:1068-1082 then reports
  #     `governor: {budgetSlots: 24, inUse: 0, queued: 0}` and `accepts.fleet: true, maxChildren: 12`
  #     (MEASURED, same minute). That is fleet capacity nothing governs: a `--profile headless`
  #     child on this node mounts no plugin-health, so it never takes a lease and `inUse` cannot
  #     ever move. Advertising it on a node with 20.8 GiB free against the 20 GiB fleet floor is
  #     exactly the fleet this script's disk rule exists to refuse.
  #
  # The honest state is the one secratary is in: no plugin-health, /healthz 404, mesh-health WARN,
  # and `/mesh/capacity` answering `oneShot: true, fleet: false` with the reason named (71 §2.1:
  # "governor ... else null"). So this step REVERTS any previous wiring, idempotently, and
  # --with-health-plugin is here for the day the probe grows a Linux path.
  local health_label="NOT wired - correct on this platform"
  if [ "$with_health_plugin" = 1 ]; then health_label="WIRED by --with-health-plugin"; fi
  say "6b. /healthz - plugin-health $health_label"
  local profile="$HOME/.dsh/profiles/web"
  local pkg="$deploy_root/packages/plugin-health"
  local i profile_ready=0 health_changed=0
  for i in $(seq 1 30); do
    if [ -f "$profile/package.json" ]; then profile_ready=1; break; fi
    sleep 1
  done
  if [ "$profile_ready" != 1 ]; then
    warn "no web profile manifest at $profile/package.json after 30 s"
  elif [ "$with_health_plugin" = 1 ] && [ -d "$pkg/lib" ]; then
    run mkdir -p "$profile/node_modules"
    if [ "$(readlink "$profile/node_modules/dsh-plugin-health" 2>/dev/null || true)" = "$pkg" ]; then
      note "$profile/node_modules/dsh-plugin-health -> $pkg (unchanged)"
    else
      run ln -sfn "$pkg" "$profile/node_modules/dsh-plugin-health"; health_changed=1
    fi
    if [ "$("$node" -e '
      const fs = require("fs"), p = process.argv[1];
      const d = JSON.parse(fs.readFileSync(p, "utf8"));
      d.dsh = d.dsh || {}; d.dsh.profile = d.dsh.profile || {};
      const b = d.dsh.profile.bundles || (d.dsh.profile.bundles = []);
      if (b.includes("dsh-plugin-health")) console.log("unchanged");
      else { b.push("dsh-plugin-health"); fs.writeFileSync(p, JSON.stringify(d, null, 2) + "\n"); console.log("added"); }
    ' "$profile/package.json")" = added ]; then health_changed=1; fi
  else
    if [ -L "$profile/node_modules/dsh-plugin-health" ]; then
      run rm -f "$profile/node_modules/dsh-plugin-health"; health_changed=1
    fi
    if [ -f "$profile/package.json" ] && [ "$("$node" -e '
      const fs = require("fs"), p = process.argv[1];
      const d = JSON.parse(fs.readFileSync(p, "utf8"));
      const b = ((d.dsh || {}).profile || {}).bundles || [];
      const i = b.indexOf("dsh-plugin-health");
      if (i < 0) console.log("absent");
      else { b.splice(i, 1); fs.writeFileSync(p, JSON.stringify(d, null, 2) + "\n"); console.log("removed"); }
    ' "$profile/package.json")" = removed ]; then health_changed=1; fi
    # The lease directory is what the gate reads as "this node has a governor". rmdir, never
    # rm -rf: it refuses to touch anything that is not already empty, so a governor that has
    # actually run here is left exactly where it is and the gate keeps telling the truth.
    if [ -d "$HOME/.dsh/governor" ]; then
      local sub gdir="$HOME/.dsh/governor"
      for sub in leases reaped waiters; do rmdir "$gdir/$sub" 2>/dev/null || true; done
      if rmdir "$gdir" 2>/dev/null; then
        note "removed the empty $gdir — no governor runs on this node, so the gate must say so"
        health_changed=1
      else
        note "$gdir kept: it is not empty, so something has really used the governor here"
      fi
    fi
    note "plugin-health not in the web profile bundles"
  fi
  if [ "$health_changed" = 1 ]; then
    # A bundle cannot hot-load (71 §0, P210). This is this node's own engine, seconds old; it is a
    # provisioning-time cost, not a runtime one, and no other machine is touched.
    run sudo -n systemctl restart dsh-engine.service
    sleep 4
  fi

  # ---------------------------------------------------------------- 7. tailscale serve
  if [ "$skip_serve" = 1 ]; then
    say "7. tailscale serve — skipped (--skip-serve)"
  else
    say "7. tailscale serve: https 443 -> 127.0.0.1:$gate_port"
    run tailscale serve status
    if tailscale serve status 2>/dev/null | grep -q "$gate_port"; then
      note "already published"
    else
      run sudo -n tailscale serve --bg "$gate_port" || warn "'tailscale serve --bg' returned non-zero — see the status below"
    fi
    run tailscale serve status
    if tailscale serve status 2>/dev/null | grep -q "$gate_port"; then
      note "PUBLISHED: https://$fqdn/ -> 127.0.0.1:$gate_port"
    else
      failures+=("tailscale serve does not show $gate_port — the node is not reachable from the tailnet")
      rc=4
    fi
  fi

  # ---------------------------------------------------------------- 8. verification
  say "8. verification"
  local i gate_root_code gate_cap_code engine_listen
  for i in 1 2 3 4 5 6 7 8 9 10; do
    curl -fsS -o /dev/null --max-time 5 "http://127.0.0.1:$gate_port/" 2>/dev/null && break
    sleep 1
  done
  # The gate does the sign-in itself, so a cold client gets the page: 200, not the engine's 401.
  gate_root_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "http://127.0.0.1:$gate_port/" || echo 000)"
  run curl -s -o /dev/null -w 'GET / -> %{http_code}\n' --max-time 20 "http://127.0.0.1:$gate_port/"
  [ "$gate_root_code" = 200 ] || { failures+=("gate / returned $gate_root_code, not 200"); rc=4; }

  gate_cap_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$gate_port/mesh/capacity" || echo 000)"
  if [ "$gate_cap_code" = 200 ]; then
    run curl -s --max-time 10 "http://127.0.0.1:$gate_port/mesh/capacity"
    printf '\n'
  else
    note "GET /mesh/capacity -> $gate_cap_code (S1 has not shipped the route to this gate copy yet)"
    failures+=("/mesh/capacity -> $gate_cap_code — stream S1 owns that route; the gate itself answers /")
  fi

  engine_listen="$(ss -tlnH 2>/dev/null | awk '{print $4}' | grep -c ":$engine_port\$" || true)"
  run ss -tlnH
  note "engine listening on :$engine_port — $engine_listen socket(s)"
  [ "${engine_listen:-0}" -ge 1 ] || { failures+=("nothing listening on :$engine_port"); rc=4; }

  # Exactly how mesh-health.ps1 asks: sign in at `/` to get the gate's cookie, then read /healthz
  # with it. Without the cookie the engine answers 401, which says nothing about health.
  local jar="$STATE_DIR/.cookie-jar" healthz_code
  curl -s -c "$jar" -o /dev/null --max-time 20 "http://127.0.0.1:$gate_port/" || true
  healthz_code="$(curl -s -b "$jar" -o /dev/null -w '%{http_code}' --max-time 20 "http://127.0.0.1:$gate_port/healthz" || echo 000)"
  run curl -s -b "$jar" -o /dev/null -w 'GET /healthz -> %{http_code}\n' --max-time 20 "http://127.0.0.1:$gate_port/healthz"
  rm -f "$jar"
  case "$healthz_code" in
    200) note "/healthz 200 — plugin-health is mounted (--with-health-plugin)" ;;
    404) note "/healthz 404 — plugin-health is not mounted. That is the documented gap and the state secratary is in: mesh-health.ps1:127-131 calls it WARN, not a fault" ;;
    *)   failures+=("GET /healthz -> $healthz_code (404 and 200 are the only expected answers)"); rc=4 ;;
  esac

  say "8b. the headless turn — the one command that proves this node can take agent work"
  local reply="$STATE_DIR/headless-verify.out"
  local errf="$STATE_DIR/headless-verify.err"
  local t0 t1 elapsed hrc
  t0="$(date +%s)"
  printf '+ cd %q && /usr/local/bin/dsh --profile headless %q   # stdout -> %s, stderr -> %s\n' \
    "$HOME/code" "Reply with exactly: $expect_reply" "$reply" "$errf"
  set +e
  ( cd "$HOME/code" && /usr/local/bin/dsh --profile headless "Reply with exactly: $expect_reply" ) \
    > "$reply" 2> "$errf"
  hrc=$?
  set -e
  t1="$(date +%s)"; elapsed=$(( t1 - t0 ))
  note "exit code: $hrc   elapsed: ${elapsed}s"
  printf -- '--- stdout ---\n'; cat "$reply" || true
  printf -- '--- stderr (tail 20) ---\n'; tail -n 20 "$errf" 2>/dev/null || true
  printf -- '--- end ---\n'
  local got_reply=""
  got_reply="$(tr -d '\r' < "$reply" | grep -o "$expect_reply" | head -1 || true)"
  if [ "$hrc" != 0 ]; then failures+=("the headless turn exited $hrc"); rc=4; fi
  if [ "$got_reply" != "$expect_reply" ]; then
    # The string matters more than the exit code: on an ancient Node the process ALSO exits 0.
    failures+=("the headless turn did not print '$expect_reply'"); rc=4
  else
    note "PROVEN: interpreter >= 22.18, credentials resolve, api.deepseek.com reachable, toolbelt mounts, session store writable"
  fi

  say "8c. services"
  run sudo -n systemctl --no-pager --lines=0 status dsh-engine.service phone-gate.service || true
  run "$node" -v
  run df -Pk "$HOME"
  run tailscale serve status || true

  # ------------------------------------------------- 8d. the settlement-crash fix
  # WHY THIS IS A PROVISIONING STEP AND NOT A ONE-OFF EDIT.
  # A child agent that has FINISHED its work can still kill its own process and lose
  # its report: the settlement watcher is a detached async IIFE with no `.catch`, and
  # the inbox getter it calls throws once the child's own scope has released the
  # projection registration (full chain: journal L3188). The runtime is an npm
  # install, so a version bump replaces the patched file and the crash comes back
  # silently — on a worker node nobody is looking at.
  #
  # The script is idempotent and sentinel-marked, and `--check` exits non-zero the
  # moment it cannot find its anchor. So a bump that invalidates the patch makes
  # PROVISIONING FAIL LOUDLY instead of quietly un-fixing the mesh.
  say "8d. settlement-crash fix on the DSH runtime"
  local patcher="${HARNESS_CONFIG_DIR:-$HOME/code/harness-config}/scripts/patch-dsh-settlement-crash.py"
  if [ ! -f "$patcher" ]; then
    warn "no patch script at $patcher — cannot guarantee a finished child's report survives its own teardown"
    failures+=("settlement-crash fix NOT verified: $patcher is absent (journal L3188)")
    rc=21
  elif ! command -v python3 >/dev/null 2>&1; then
    warn "python3 is absent, so the settlement-crash fix cannot be checked or applied on this node"
    failures+=("settlement-crash fix NOT verified: no python3 (journal L3188)")
    rc=21
  else
    # `--check` first: only edit the vendor tree when the fix is actually missing.
    if python3 "$patcher" --check --root "$deploy_root/node_modules/@deepseek-ai" >/dev/null 2>&1; then
      note "ACCEPT the DSH runtime is already patched against the settlement crash"
    else
      note "applying the settlement-crash fix to $deploy_root/node_modules/@deepseek-ai"
      if run python3 "$patcher" --root "$deploy_root/node_modules/@deepseek-ai"; then
        if python3 "$patcher" --check --root "$deploy_root/node_modules/@deepseek-ai" >/dev/null 2>&1; then
          note "ACCEPT applied and re-verified"
        else
          warn "the settlement-crash fix did NOT verify after applying — a finished child can still lose its report here"
          failures+=("settlement-crash fix applied but failed verification (journal L3188)")
          rc=21
        fi
      else
        warn "the settlement-crash fix could not be applied — the runtime changed underneath it"
        failures+=("settlement-crash fix NOT applied: the anchor moved (journal L3188) — re-derive the patch for this version")
        rc=21
      fi
    fi
  fi

  # ---------------------------------------------------------------- 9. worktree root
  say "9. fleet worktree root"
  local wr_ok=0 wr_reason=""
  if [ "$avail_gib" -ge "$min_work_free_gib" ]; then
    run mkdir -p "$work_root"
    wr_ok=1; wr_reason="ok"
    note "ACCEPT $work_root: ${avail_gib} GiB free >= $min_work_free_gib"
  else
    wr_reason="refused: ${avail_gib} GiB free < ${min_work_free_gib} GiB"
    warn "REFUSED to establish the fleet worktree root $work_root — $wr_reason"
    warn "the node still runs one-shot agent turns; it must NOT be sent a fleet (71 §2.2 disk rule)"
    rc=20
  fi
  local wr_bool=false
  if [ "$wr_ok" = 1 ]; then wr_bool=true; fi
  printf '{"schema":1,"node":"%s","fqdn":"%s","at":"%s","workRoot":{"path":"%s","freeGiB":%s,"acceptsFleet":%s,"reason":"%s"}}\n' \
    "$host_name" "$fqdn" "$(date -u +%FT%TZ)" "$work_root" "$avail_gib" "$wr_bool" "$wr_reason" \
    > "$STATE_DIR/workroot.json"
  note "verdict written to $STATE_DIR/workroot.json"

  # ---------------------------------------------------------------- 10. summary
  local over=ok
  if [ "$rc" = 4 ]; then over=verification-failed
  elif [ "$rc" = 20 ]; then over="ok (fleet worktree root refused: ${avail_gib} GiB free)"
  elif [ "$rc" != 0 ]; then over=step-failed; fi
  {
    printf '{"schema":1,"stream":"S2","node":"%s","fqdn":"%s","at":"%s","verdict":"%s","exit":%s,' \
      "$host_name" "$fqdn" "$(date -u +%FT%TZ)" "$over" "$rc"
    printf '"node":{"version":"%s","path":"%s"},"dsh":{"version":"%s","path":"%s"},' \
      "$("$node" -v)" "$node_link/bin/node" "$dsh_version" "$dsh_bin"
    printf '"enginePort":%s,"gatePort":%s,"deployRoot":"%s","envFile":"%s","workRoot":"%s","freeGiB":%s,' \
      "$engine_port" "$gate_port" "$deploy_root" "$env_file" "$work_root" "$avail_gib"
    printf '"headless":{"exit":%s,"seconds":%s,"stdout":%s},"log":"%s"}\n' \
      "$hrc" "$elapsed" "$("$node" -p 'JSON.stringify(process.argv[1])' "$(tr -d '\n' < "$reply" | head -c 200)")" "$LOG"
  } > "$STATE_DIR/provisioned.json"
  run cat "$STATE_DIR/provisioned.json"

  if [ "${#failures[@]}" -gt 0 ]; then
    say "NOTES / FAILURES"
    local f
    for f in "${failures[@]}"; do printf '   - %s\n' "$f"; done
  fi
  say "S2 done — $over"
  return "$rc"
}

# ------------------------------------------------------------------------------ dispatch
# Both halves run with errexit ON, in a subshell, so that a failure anywhere aborts the half while
# the parent can still read the code out and return it to the caller unchanged.
rc=0
if [ "$remote" = 1 ]; then
  STATE_DIR="${STATE_DIR:-$HOME/.dsh-mesh}"
  LOG_DIR="${LOG_DIR:-$HOME/.dsh-phone}"
  mkdir -p "$STATE_DIR" "$LOG_DIR"
  LOG="$STATE_DIR/provision-$(date -u +%Y%m%dT%H%M%SZ).log"
  # tee, so the caller sees the same transcript the node keeps. PIPESTATUS carries the half's own
  # exit code out of the pipe.
  set +e
  { set -e; remote_half; } 2>&1 | tee -a "$LOG"
  rc="${PIPESTATUS[0]}"
  set -e
  printf 'S2_EXIT=%s\n' "$rc" >> "$LOG"
  exit "$rc"
else
  set +e
  ( set -e; local_half )
  rc=$?
  set -e
  exit "$rc"
fi
