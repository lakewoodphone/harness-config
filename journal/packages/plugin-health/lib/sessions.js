/**
 * Session and agent-loop census, plus the engine's own resource counters.
 *
 * WHAT THIS COUNTS, AND WHY EACH NUMBER IS THE ONE THAT MATTERS
 * The engine is one OS process serving every window; a session is an in-memory
 * object, a subagent is the same process again, and only a shell tool call
 * becomes another process. So "how loaded is it" cannot be read from a process
 * count — it is four different numbers, and they are all here:
 *
 *   sessionsLive      every live Agent in the registry (windows + subagents)
 *   sessionsRoot      live Agents created without an owning agent (the windows)
 *   sessionsRunning   Agents whose public status is `running` — this is the
 *                     "agent loop actually executing right now" count, and the
 *                     only one that says whether work is in flight
 *   subagentStrings   live Agents owned by another agent
 *
 * `list()` allocates a fresh array each call, so this is O(live agents) with no
 * I/O and no shared mutable state. It is cheap enough to call on a timer.
 */

/** Nothing here reads a field it does not need: live Agent objects are internal. */
export function censusAgents(agents) {
  const empty = { sessionsLive: 0, sessionsRoot: 0, sessionsRunning: 0, subagentsLive: 0, sessions: [] };
  if (agents === undefined || typeof agents.list !== 'function') return { ...empty, unavailable: 'the agents service is not mounted' };
  let live = [];
  try {
    live = agents.list();
  } catch (error) {
    return { ...empty, unavailable: `agents.list() threw: ${error instanceof Error ? error.message : String(error)}` };
  }
  let root = 0;
  let running = 0;
  let subagents = 0;
  const sessions = [];
  for (const agent of live) {
    const owned = agent.owner !== undefined && agent.owner !== null;
    if (owned) subagents += 1;
    else root += 1;
    const status = agent.status;
    if (status === 'running') running += 1;
    // Scalar leaves only, never the Agent object: id, ownership and status are
    // all this census is entitled to read.
    sessions.push({ id: String(agent.id), status: status === 'running' ? 'running' : 'idle', subagent: owned });
  }
  return {
    sessionsLive: live.length,
    sessionsRoot: root,
    sessionsRunning: running,
    subagentsLive: subagents,
    sessions,
  };
}

/** Process-wide memory, in bytes, exactly as `process.memoryUsage()` reports it. */
export function memoryOf(proc) {
  const usage = proc.memoryUsage();
  return {
    rss: usage.rss,
    heapTotal: usage.heapTotal,
    heapUsed: usage.heapUsed,
    external: usage.external,
    arrayBuffers: usage.arrayBuffers,
    heapLimit: typeof proc.constrainedMemory === 'function' ? proc.constrainedMemory() : 0,
  };
}

/**
 * Engine identity and age.
 *
 * `uptimeMs` is monotonic process uptime, not wall-clock arithmetic, because a
 * clock step would otherwise make the engine appear to have restarted. The wall
 * start stamp is carried separately so a reader can prove *which* engine it is
 * looking at — the single most important field in this whole surface, after the
 * incident in which a stale copy of a database was read and believed.
 */
export function identityOf(proc, startedAtMs) {
  return {
    pid: proc.pid,
    startedAt: new Date(startedAtMs).toISOString(),
    uptimeMs: Math.round(proc.uptime() * 1000),
    node: proc.version,
    platform: proc.platform,
    arch: proc.arch,
    cwd: proc.cwd(),
    execPath: proc.execPath,
    argv: proc.argv.filter((part) => typeof part === 'string').slice(0, 12),
    env: {
      dshHome: proc.env.DSH_HOME ?? null,
      dshWebUrl: proc.env.DSH_WEB_URL ?? null,
      dshWebMode: proc.env.DSH_WEB_MODE ?? null,
    },
  };
}

/** Human-readable age, for the rendered text surfaces. */
export function humanAge(ms) {
  if (!Number.isFinite(ms) || ms < 0) return 'unknown';
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m${String(seconds % 60).padStart(2, '0')}s`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h${String(minutes % 60).padStart(2, '0')}m`;
  return `${Math.floor(hours / 24)}d${String(hours % 24).padStart(2, '0')}h`;
}

/** Bytes as MiB with one decimal, the unit the operator's own notes use. */
export function mib(bytes) {
  if (!Number.isFinite(bytes)) return null;
  return Math.round((bytes / (1024 * 1024)) * 10) / 10;
}
