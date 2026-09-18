/**
 * Classification of the OS process table into the four things that actually cost
 * this machine something.
 *
 * THE ONE FACT THIS ENCODES
 * The engine is a single OS process. A session is not a process, a subagent is
 * not a process, and an MCP bridge is not per session — but a shell tool call
 * IS two processes (a `runner.js` Job owner plus the shell), and a leaked MCP
 * generation IS a family of processes that nothing reaps. So:
 *
 *   runner   — a direct child of the engine running node: the Job owner for an
 *              in-flight shell tool call. This is the number that says how much
 *              shell work is happening right now, and it is the number the
 *              admission governor is trying to keep from exploding.
 *   mcp      — a descendant of the engine whose image path matches a known MCP
 *              server package. Counted per server name, because "four fetch
 *              stacks alive at once" is the measured waste this surface exists
 *              to make visible.
 *   engine   — the engine row itself.
 *   other    — everything else, counted but not listed: the browser windows and
 *              the editor are not the engine's business.
 *
 * DIRECT-CHILD IS THE RUNNER RULE, and it is deliberately that narrow. The MCP
 * bridges are spawned by the MCP SDK through `cross-spawn`, never through
 * `dsh-subprocess-local`, so an MCP server is a child of a `cmd.exe` or a
 * launcher python, never a direct child of the engine. A node process that is a
 * direct child of the engine is therefore a tool-call runner (or a background
 * job's runner, which is the same cost class). Measured on ZABZ-YOGA
 * 2026-09-16: 3 direct node children while 3 shell hosts were live.
 *
 * WHAT THIS DOES NOT DO: it never reads a command line, because the snapshot
 * has none (see `snapshot.ps1`). Classification is parent + image path only.
 */

/** MCP server package names, as they appear in an image path. */
const MCP_MARKERS = [
  { server: 'fetch', markers: ['mcp-fetch-server', 'mcp_fetch_server'] },
  { server: 'playwright', markers: ['@playwright', 'playwright\\mcp', 'playwright/mcp'] },
  { server: 'firecrawl', markers: ['firecrawl-mcp', 'firecrawl_mcp'] },
  { server: 'jina', markers: ['mcp-remote', 'mcp_remote'] },
  { server: 'context7', markers: ['context7-mcp', 'context7_mcp'] },
  { server: 'secretary', markers: ['ps_mcp_server.py', 'ps-mcp-server'] },
];

const isNodeName = (name) => typeof name === 'string' && /^node(\.exe)?$/i.test(name);

/** Which MCP server an image path belongs to, or undefined. */
export function mcpServerOf(image) {
  if (typeof image !== 'string' || image.length === 0) return undefined;
  const lower = image.toLowerCase();
  for (const entry of MCP_MARKERS) {
    for (const marker of entry.markers) {
      if (lower.includes(marker.toLowerCase())) return entry.server;
    }
  }
  return undefined;
}

/** One compact row, scalars only — the process object itself is never retained. */
function rowOf(process, depth) {
  return {
    pid: process.pid,
    ppid: process.ppid,
    depth,
    name: process.name ?? '',
    image: typeof process.image === 'string' ? process.image : '',
    threads: Number.isFinite(process.threads) ? process.threads : 0,
    workingSetBytes: Number.isFinite(process.workingSetBytes) ? process.workingSetBytes : 0,
    privateBytes: Number.isFinite(process.privateBytes) ? process.privateBytes : 0,
    handles: Number.isFinite(process.handles) ? process.handles : -1,
  };
}

/**
 * Walk the process table from the engine outward.
 *
 * @param {object} snapshot - a parsed `snapshot.ps1` document
 * @param {object} [options]
 * @param {number} [options.maxDepth] deepest ancestry walk, so a corrupt
 *   parent chain cannot spin
 * @returns {{runner: object[], mcp: object[], byServer: object, engine: object|null, other: number, nodeProcesses: number, maxDepth: number}}
 */
export function classifyProcesses(snapshot, { maxDepth = 6 } = {}) {
  const empty = { runner: [], mcp: [], byServer: {}, engine: null, other: 0, nodeProcesses: 0, maxDepth: 0, children: 0 };
  if (snapshot === null || typeof snapshot !== 'object') return empty;
  const enginePid = snapshot.enginePid;
  const list = Array.isArray(snapshot.processes) ? snapshot.processes : [];
  if (!Number.isInteger(enginePid)) return empty;

  const byPid = new Map();
  for (const process of list) byPid.set(process.pid, process);

  /** Ancestry depth from the engine, or undefined when unrelated. */
  const depthOf = (process) => {
    let depth = 0;
    let cursor = process;
    const seen = new Set();
    while (depth <= maxDepth) {
      const parentPid = cursor.ppid;
      if (parentPid === enginePid) return depth + 1;
      if (parentPid === 0 || seen.has(parentPid)) return undefined;
      const parent = byPid.get(parentPid);
      if (parent === undefined) return undefined;
      seen.add(parentPid);
      cursor = parent;
      depth += 1;
    }
    return undefined;
  };

  const result = { runner: [], mcp: [], byServer: {}, engine: null, other: 0, nodeProcesses: 0, maxDepth: 0, children: 0 };
  for (const process of list) {
    if (process.pid === enginePid) {
      result.engine = rowOf(process, 0);
      continue;
    }
    if (isNodeName(process.name)) result.nodeProcesses += 1;
    const depth = depthOf(process);
    if (depth === undefined) {
      result.other += 1;
      continue;
    }
    if (depth > result.maxDepth) result.maxDepth = depth;
    if (depth === 1) result.children += 1;
    const row = rowOf(process, depth);
    // Direct child of the engine that is node = a tool-call runner. See header.
    if (depth === 1 && isNodeName(process.name)) {
      result.runner.push({ ...row, kind: 'runner' });
      continue;
    }
    const server = mcpServerOf(process.image);
    if (server !== undefined) {
      row.server = server;
      result.mcp.push(row);
      result.byServer[server] = (result.byServer[server] ?? 0) + 1;
      continue;
    }
    result.other += 1;
  }
  result.runner.sort((a, b) => a.pid - b.pid);
  result.mcp.sort((a, b) => (a.server < b.server ? -1 : a.server > b.server ? 1 : a.pid - b.pid));
  // The engine row is excluded from other/descendant arithmetic; these counters
  // count what is *below* it.
  result.other -= 0;
  return result;
}

/** Total private bytes of a set of rows, for the cost lines. */
export function privateBytesOf(rows) {
  let total = 0;
  for (const row of rows) total += row.privateBytes > 0 ? row.privateBytes : row.workingSetBytes;
  return total;
}
