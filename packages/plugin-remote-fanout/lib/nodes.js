/**
 * The mesh node table: everything about a node that only a DISPATCHER can know,
 * keyed by the name the BROKER names it with.
 *
 * WHY THIS IS SHARED AND NOT COPIED
 * `bin/mesh-run.mjs` carried this table alone until 2026-09-17. Placement moved
 * into the provider, and the provider needs the same facts for the same node
 * names; two tables would drift and the drift would be invisible until a child
 * landed somewhere it could not run. So the table moved here and both callers
 * import it. `lib/nodes.js` has no imports and no I/O, so it is as unit-testable
 * as `remote-script.js`.
 *
 * WHY THE KEY IS THE BROKER'S NAME AND NOT THE SSH ALIAS
 * The broker's roster names nodes by their Tailscale DNS label
 * (`zabz-yoga-1`, not `zabz-yoga`) because the capacity contract's invariant is
 * `node === fqdn.split(".")[0]`. A placement decision is only actionable if the
 * name in it can be turned back into an ssh destination, so that translation is
 * data, and it is here.
 *
 * WHY `verified` IS A FIELD AND NOT A COMMENT
 * An empty result is not health and an unverified path is not a placement. A
 * node whose two paths were never measured still dispatches — the broker's rule
 * is queue-never-amputate, not refuse-unmeasured — but the fact travels with the
 * row so a failure can be read instead of guessed at.
 */

/**
 * THE CREDENTIAL ENV FILE, AND WHY IT IS THE POINT OF THIS FILE
 *
 * A node can be provisioned two ways, and they are NOT equivalent:
 *
 *   * with a `dsh` EXECUTOR (a wrapper on PATH — the mesh installer writes
 *     `/usr/local/bin/dsh`). The wrapper resolves the interpreter, sources the
 *     worker's credential file and then execs `node bin.js "$@"`. It is the
 *     machine's own contract for "how a worker is launched here".
 *   * with an INTERPRETER (`node <dsh>/lib/bin.js ...`), which is a plain
 *     process and inherits whatever environment it is spawned with.
 *
 * A dispatcher that names an interpreter and a `bin.js` bypasses the wrapper,
 * and therefore bypasses the ONLY thing that sources the credential. Measured
 * 2026-09-17 on `zabz-tech-linux`: the wrapper form completes a real child turn
 * (`LINUX NODE OK`, exit 0, 3 s) while the direct pair that the dispatcher
 * actually ran died with `MISSING_CREDENTIAL: llm-deepseek` — and, before that,
 * with exit 127, because a version-stamped interpreter path in this table had
 * rotted. `DEEPSEEK_API_KEY` is in a root-owned file readable only by the worker
 * group, sourced by the wrapper and by nothing else: not `env`, not
 * `bash -lc`, not `bash -c` (all three measured).
 *
 * So: WHERE A WRAPPER EXISTS, INVOKE IT BY NAME. The interpreter pair is the
 * fallback for a node that has no wrapper, and a flag was measured on the wrong
 * side of this distinction once already — this file is where that fact lives.
 */
export const DEFAULT_WORKER_ENV_FILES = Object.freeze(['/etc/dsh-worker.env']);

/**
 * @typedef {object} NodeFacts
 * @property {string} ssh      the ssh destination (an alias from ~/.ssh/config, or user@host)
 * @property {string[]} hosts  hostnames this destination is allowed to report (`71` §2.4)
 * @property {'powershell'|'posix'} shell  the remote shell the child runs under
 * @property {string} [command] an EXECUTOR on PATH that launches a worker (the mesh `dsh` wrapper);
 *                             when present it is preferred over `driver`+`bin`
 * @property {string} [credentialEnvFiles] files the executor sources, recorded so the credential
 *                             source is stated rather than assumed
 * @property {string} [driver]  fallback interpreter path ON THAT NODE (the old `nodeExe`)
 * @property {string} [bin]     fallback `@deepseek-ai/dsh/lib/bin.js` path ON THAT NODE
 * @property {string} cwd      working directory for the child turn
 * @property {string} verified when those facts were last measured, and how
 */

/** @type {Record<string, NodeFacts>} */
export const NODES = {
  'zabz-tech': {
    ssh: 'desktop-ts',
    hosts: ['ZABZ-TECH', 'zabz-tech', 'zabz-tech.tail93e6e6.ts.net'],
    shell: 'powershell',
    driver: 'C:/Program Files/nodejs/node.exe',
    // THE FROZEN PIN, NOT THE npx CACHE (2026-10-08). This row named the npx path and the
    // npx cache on THIS node still holds 0.1.5-rc.1 while the synced profile patches name
    // 0.1.7-line packages (`@deepseek-ai/dsh-agent-preset`, `-registry`, `dsh-workflow-ptc`),
    // so a row that dispatches here was pointing at an engine that cannot load the config
    // this fleet ships. The owner's machine spent 2026-10-07/08 in a boot crash loop on
    // exactly that mismatch and was fixed the same day by installing `~/.dsh/engine` at
    // 0.2.0-rc.2. The lesson is dshw.ps1's own: a path a stray `npx` can rewrite is not a pin.
    bin: 'C:/Users/ezabz/.dsh/engine/node_modules/@deepseek-ai/dsh/lib/bin.js',
    cwd: 'C:/Users/ezabz',
    verified: 'RE-MEASURED 2026-10-08: node v24.19.0, dsh 0.2.0-rc.2 from the frozen pin `~/.dsh/engine`, and a live child turn through this row (`--profile headless "Reply with exactly: TECH_OK"`) answered exactly TECH_OK, exit 0. The npx cache on this node is STILL 0.1.5-rc.1 -- do not point this row back at it. Historic note (2026-09-17): node v24.19.0, dsh 0.1.5-rc.1, a child turn completed over ssh. Windows has no `dsh` executor on PATH, so this node uses the INTERPRETER form and the credential comes from the engine\'s own environment (`env` is measured: the parent engine is already running with its key).',
  },
  // Keyed on the Tailscale DNS label: the capacity contract's invariant is
  // `node === fqdn.split(".")[0]`, so this label is what a broker answer names.
  'zabz-yoga-1': {
    ssh: 'laptop-ts',
    hosts: ['ZABZ-YOGA', 'zabz-yoga', 'zabz-yoga-1', 'zabz-yoga-1.tail93e6e6.ts.net'],
    shell: 'powershell',
    driver: 'C:/Program Files/nodejs/node.exe',
    // THE SAME PIN AS `zabz-tech`, SAME REASON (2026-10-08): the npx cache is not a pin on
    // either Windows node. Here it happens to hold 0.2.0-rc.2 today, which is exactly the
    // problem -- the row would be correct by luck and the luck is revocable by any `npx`.
    bin: 'C:/Users/ezabz/.dsh/engine/node_modules/@deepseek-ai/dsh/lib/bin.js',
    cwd: 'C:/Users/ezabz',
    verified: 'RE-MEASURED 2026-10-08: dsh 0.2.0-rc.2 from the frozen pin `~/.dsh/engine`, which is also the engine this host runs and which composes the web profile cleanly (`--profile web --dump-config` exit 0, 133,893 B, empty stderr). HISTORIC: MEASURED 2026-09-17: node v24.12.0, dsh 0.1.5-rc.1. INTERPRETER form (no `dsh` executor on PATH). ACCEPTED v1 ssh work after its module links were recreated INSIDE an ssh session (413 links, 22 s): `ssh <laptop> dsh --profile headless "Reply with exactly: LAPTOP OK"` -> LAPTOP OK, exit 0, 10.3 s. Before that relink it refused every reparse point as UNTRUSTED (70-remote-fanout-proof.md §4.4)',
  },
  // THE EXECUTOR FORM, AND THE MEASUREMENT THAT PUT IT HERE. Read `§4` of
  // docs/mesh/102-linux-dispatch.md before changing this row.
  'zabz-tech-linux': {
    ssh: 'linux-pc-ts',
    hosts: ['zabz-tech-linux'],
    shell: 'posix',
    // Discovered, not assumed: `command -v dsh` on this node answers
    // /usr/local/bin/dsh (installed by scripts/provision-mesh-node.sh, root
    // owned, and it resolves BOTH the interpreter and the credential file from
    // $HOME, so nothing here names a Node version).
    command: 'dsh',
    credentialEnvFiles: ['/etc/dsh-worker.env'],
    // The interpreter path is the FALLBACK only, and it is the version-FREE
    // symlink this node's own wrapper uses — the version-stamped
    // `/home/zabz/.local/node-v24.12.0-linux-x64/bin/node` that used to be here
    // does not exist on the machine (exit 127) and the install that would have
    // created it was never run in that form (62-worker-runtime.md §3.1).
    driver: '/usr/local/bin/node',
    // MEASURED 2026-10-08 AND LEFT ALONE ON PURPOSE: this node's ONLY install is the
    // 0.1.5-rc.1 `~/dsh-engine` (no `dsh-current`, and it lacks the three 0.1.7-line
    // packages). The `command: 'dsh'` executor above is what actually runs children here,
    // and this `bin` is the fallback, so nothing is broken today -- the headless profile a
    // child loads was measured to compose cleanly under 0.1.5. But this row now names a
    // DIFFERENT engine line from the one the profile patches ship, which is the exact seam
    // that took `zabz-tech` down on 2026-10-07/08. Provision this node at 0.2.0-rc.2 (and
    // repoint the executor wrapper) before relying on its fallback path.
    bin: '/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js',
    cwd: '/home/zabz/code',
    verified: 'MEASURED 2026-10-08: `/home/zabz/dsh-engine` = dsh 0.1.5-rc.1, MISSING @deepseek-ai/dsh-agent-preset, -preset-registry and dsh-workflow-ptc; there is no `~/dsh-current` on this node. The 2026-09-17 note below still stands for the mechanism. HISTORIC: MEASURED 2026-09-17T14:34-14:40Z from a Windows dispatcher: `command -v dsh` -> /usr/local/bin/dsh; `command -v node` -> /usr/local/bin/node -> /home/zabz/.local/node/bin/node (v22.23.2); /etc/dsh-worker.env readable by the worker; /home/zabz/.local/node-v24.12.0-linux-x64/bin/node ABSENT (the old row, exit 127). A real v1 child turn through this row completed over ssh (`MESH-HOST: zabz-tech-linux`, exit 0) once the executor was used. The 2026-09-16 note "no Node runtime yet" is STALE.',
  },
  secratary: {
    ssh: 'secratary-ts',
    hosts: ['secratary'],
    shell: 'posix',
    driver: '/home/zabz/node/bin/node',
    // `~dsh-current`, NOT `~/dsh-engine` (2026-10-08). `dsh-current` is the version-FREE
    // symlink this host's own engine runs from (`-> /home/zabz/dsh-install/0.2.0-rc.2`), so
    // it follows a promotion instead of pinning this row to a version. `~/dsh-engine` is a
    // 0.1.5-rc.1 leftover MEASURED to lack every 0.1.7-line package the fleet's profiles
    // name (`dsh-agent-preset`, `-registry`, `dsh-workflow-ptc`).
    bin: '/home/zabz/dsh-current/node_modules/@deepseek-ai/dsh/lib/bin.js',
    cwd: '/home/zabz/code',
    verified: 'RE-MEASURED 2026-10-08: `dsh-current -> /home/zabz/dsh-install/0.2.0-rc.2`; a live child turn through this row (`--profile headless "Reply with exactly: SEC_OK"`) answered exactly SEC_OK, exit 0. HISTORIC: MEASURED 2026-09-16 (62 §1.2): node v22.23.2 at /home/zabz/node/bin/node; the dsh install is the one the systemd engine runs from. RE-CONFIRMED 2026-09-17 over ssh: INTERPRETER form — `command -v dsh` answers NOTHING and there is no /etc/dsh-worker.env, so this row has no executor and carries no credential env file; its long-lived dsh processes inherit the key from the service environment.',
  },
  lakewooechsmini: {
    ssh: 'mac-mini-ts',
    hosts: ['LakewooechsMini'],
    shell: 'posix',
    driver: '/usr/local/bin/node',
    bin: '/Users/lpt/.dsh-install/node_modules/@deepseek-ai/dsh/lib/bin.js',
    cwd: '/Users/lpt/lpt-hub',
    // THE CREDENTIAL IS THE NODE'S OWN, and the marker says so rather than saying "none". Measured
    // 2026-09-18: `/Users/lpt/.dsh/.credentials.yaml` exists (-rw------- 277 B) because this machine
    // runs its own DSH engine; `/etc/dsh-worker.env` and `~/.dsh-install/.credentials.yaml` are ABSENT.
    // An empty list here is an unanswered question, which is why the test that caught this row fired
    // the moment the broker roster began to claim v1 work for this node.
    credentialEnvFiles: ['!self-store'],
    verified: 'MEASURED 2026-09-16 (62 §3.2) for the two paths; RE-CONFIRMED 2026-09-17 over ssh: INTERPRETER form (`command -v dsh` empty, no worker env file), /usr/local/bin/node -> /usr/local/lib/nodejs/node-v24.19.0-darwin-arm64/bin/node. EXERCISED AS A WORKER 2026-09-18: `ssh mac-mini-ts "/usr/local/bin/node /Users/lpt/.dsh-install/node_modules/@deepseek-ai/dsh/lib/bin.js --profile headless \'Reply with exactly: MACMINI_OK\'"` -> exit 0 in 2948 ms, stdout exactly MACMINI_OK, and its gate answers https://lakewooechsmini.tail93e6e6.ts.net/mesh/capacity with HTTP 200. The credential is the node\'s own store, above.',
  },
};

/** Every node name this dispatcher can turn into a destination. */
export function nodeNames() {
  return Object.keys(NODES);
}

/** The facts for one broker-named node, or `undefined` when it is not dispatchable. */
export function factsForNode(node) {
  return NODES[node];
}

/**
 * Read a roster row through ONE spelling.
 *
 * `driver`/`bin` are the names this table uses now; `nodeExe`/`dshBin` are what
 * the fixed-mode profile rows and the pre-2026-09-17 table carried, and they are
 * READ, never produced — a caller that has not moved must not silently lose its
 * invocation. This is the only place the two spellings meet.
 */
export function normalizeNodeFacts(facts) {
  if (facts === undefined || facts === null) return undefined;
  const driver = facts.driver ?? facts.nodeExe;
  const bin = facts.bin ?? facts.dshBin;
  return {
    ...facts,
    driver: driver === undefined ? undefined : String(driver),
    bin: bin === undefined ? undefined : String(bin),
  };
}

/**
 * How to invoke a worker on a node — ONE decision, in ONE place.
 *
 * Order, and it is the whole point of this file:
 *   1. `command` — an EXECUTOR on PATH (the mesh `dsh` wrapper). It resolves the
 *      interpreter itself and sources the credential file. Nothing is hardcoded
 *      and the credential is supplied by the machine's own contract.
 *   2. `driver` + `bin` — an explicit interpreter pair. This is the fallback for
 *      a node with no executor, and for every Windows node.
 *
 * Why a TABLE and not a live probe: the dispatcher runs one ssh per child and
 * already spends one on the turn itself; a probe per dispatch would double the
 * ssh cost to answer a question whose answer changes only when the machine is
 * re-provisioned. So the DISCOVERY (`command -v dsh`, `command -v node`, the
 * credential file's mode) is recorded in `verified`, dated, with the commands
 * that produced it — and the test below fails when the recorded form cannot be
 * resolved, which is the check that caught the version-stamped path.
 *
 * @param {Partial<NodeFacts>|undefined} raw a roster row (or a fixed-mode config)
 * @returns {{form:'executor'|'interpreter', command:string, argvPrefix:string[]|undefined,
 *            driver:string|undefined, bin:string|undefined,
 *            credentialEnvFiles:string[], credentialSource:string}|undefined}
 */
export function resolveNodeInvocation(raw) {
  const facts = normalizeNodeFacts(raw);
  if (facts === undefined) return undefined;
  const envFiles = Array.isArray(facts.credentialEnvFiles)
    ? facts.credentialEnvFiles.map(String).filter((value) => value !== '')
    : [];
  if (typeof facts.command === 'string' && facts.command.trim() !== '') {
    return {
      form: 'executor',
      command: facts.command.trim(),
      argvPrefix: undefined,
      driver: facts.driver,
      bin: facts.bin,
      credentialEnvFiles: envFiles,
      credentialSource: envFiles.length > 0
        ? `the executor sources ${envFiles.join(', ')} itself`
        : `the executor \`${facts.command.trim()}\` sources the worker environment itself`,
    };
  }
  if (!(typeof facts.driver === 'string' && facts.driver !== '') || !(typeof facts.bin === 'string' && facts.bin !== '')) {
    return undefined;
  }
  // A POSIX node without an executor must be told where the credential is, or
  // the invocation cannot carry one — which is exactly the defect this table's
  // `zabz-tech-linux` row had. A leading `!` in `credentialEnvFiles` is a
  // positive record that the node was CHECKED and has none; an empty list is an
  // unanswered question and the tests below say so.
  const posix = facts.shell === 'posix';
  const checkedNoEnvFile = envFiles.some((file) => file.startsWith('!'));
  // `!self-store` is the POSITIVE record that this node supplies its OWN credential: it runs a DSH
  // engine, so it has a `~/.dsh/.credentials.yaml` and there is no worker env file to source. That is
  // a different fact from "checked and has none", and collapsing the two would print the wrong
  // sentence about a machine whose credential is real and local. Measured 2026-09-18 on
  // `lakewooechsmini`: `/Users/lpt/.dsh/.credentials.yaml` exists (mode 600, 277 B) while
  // `/etc/dsh-worker.env` and `~/.dsh-install/.credentials.yaml` are both absent.
  const selfStore = envFiles.some((file) => file.startsWith('!self-store'));
  const usable = envFiles.filter((file) => !file.startsWith('!'));
  return {
    form: 'interpreter',
    command: facts.driver,
    argvPrefix: [facts.bin],
    driver: facts.driver,
    bin: facts.bin,
    credentialEnvFiles: usable,
    credentialSource: usable.length > 0
      ? `the interpreter form sources ${usable.join(', ')} before it runs (the wrapper it bypasses would have)`
      : selfStore
        ? 'the node supplies its own credential (a DSH credential store of its own, measured 2026-09-18); there is no worker env file to source and none is needed'
        : checkedNoEnvFile || !posix
          ? 'the interpreter inherits its credential from the dispatching process environment'
          : 'UNKNOWN — nothing in this row says where a credential comes from',
  };
}

/** The resolved invocation for a broker-named node, or `undefined` for an unknown node. */
export function invocationForNode(node) {
  return resolveNodeInvocation(NODES[node]);
}

/** True when a row can produce a command at all, whichever form it declares. */
export function invocationResolvable(node) {
  return invocationForNode(node) !== undefined;
}

/**
 * A host token worth comparing: not the `(not reported)` placeholder a report
 * writes when a child never ran, and not an empty string.
 */
export function isHostToken(value) {
  return /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(String(value ?? ''));
}

/** Case-insensitive, domain-suffix-blind, `-ts`-blind comparison of two host names. */
export function normalizeHost(value) {
  return String(value ?? '').trim().toLowerCase().split('.')[0].replace(/-ts$/, '');
}

/**
 * Which hostnames may legitimately report themselves as a given node. An
 * unknown node falls back to its own name — never to "anything", because a
 * lookup miss must not widen the check that exists to catch a wrong machine.
 */
export function hostMatchesNode(host, node) {
  const allowed = NODES[node]?.hosts ?? [node];
  const normalized = normalizeHost(host);
  return allowed.some((candidate) => normalizeHost(candidate) === normalized);
}
