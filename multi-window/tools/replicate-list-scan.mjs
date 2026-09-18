// replicate-list-scan.mjs — time, in plain Node, exactly the filesystem work that
// dsh-session-persistence-jsonl's `listArtifacts` does for one `session/list` call.
//
// WHY: `POST /api/session/list` measured 8.5-42 s against the live engine while every other RPC
// in the same page load answered 200 promptly. That separates "the engine's event loop is
// saturated" from "this one code path is expensive". If the same filesystem work is fast here,
// the cost is inside the engine's own async pipeline, not in the disk.
//
// What the real code does per session (dsh-session-persistence-jsonl/lib/index.js):
//   listProjectDirs()            -> readdir of the sessions root
//   listSessionDirs(project)     -> readdir of each project dir
//   resolveGenerationInDirectory -> readdir to pick the generation file
//   readGenerationHeader()       -> readFirstZstdLine(sourcePath) + JSON.parse
//   list()                       -> stat(path, {bigint:true}) per artifact
import { readdir, stat, open } from 'node:fs/promises'
import { zstdDecompressSync } from 'node:zlib'
import path from 'node:path'
import os from 'node:os'

const root = process.argv[2] ?? path.join(os.homedir(), '.dsh', 'sessions')

const t0 = performance.now()
const projects = (await readdir(root, { withFileTypes: true })).filter((d) => d.isDirectory())
const t1 = performance.now()

const sessions = []
for (const project of projects) {
  const dir = path.join(root, project.name)
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) sessions.push(path.join(dir, entry.name))
  }
}
const t2 = performance.now()

// read the first zstd line of each session's newest generation file
let parsed = 0
let bytesRead = 0
for (const sessionDir of sessions) {
  const files = (await readdir(sessionDir)).filter((f) => f.endsWith('.zstd'))
  if (files.length === 0) continue
  const file = path.join(sessionDir, files.sort().at(-1))
  const fh = await open(file, 'r')
  try {
    const buf = Buffer.alloc(64 * 1024)
    const { bytesRead: n } = await fh.read(buf, 0, buf.length, 0)
    bytesRead += n
    try {
      const out = zstdDecompressSync(buf.subarray(0, n))
      const nl = out.indexOf(10)
      if (nl > 0) { JSON.parse(out.subarray(0, nl).toString('utf8')); parsed++ }
    } catch { /* truncated first frame is expected; the real code streams until one line */ }
  } finally { await fh.close() }
}
const t3 = performance.now()

let stats = 0
for (const sessionDir of sessions) {
  const files = (await readdir(sessionDir)).filter((f) => f.endsWith('.zstd'))
  if (files.length === 0) continue
  await stat(path.join(sessionDir, files.sort().at(-1)), { bigint: true })
  stats++
}
const t4 = performance.now()

const r = (a, b) => `${(b - a).toFixed(0)} ms`
console.log(`root                 : ${root}`)
console.log(`project dirs         : ${projects.length}                      ${r(t0, t1)}`)
console.log(`session dirs         : ${sessions.length}                    ${r(t1, t2)}`)
console.log(`first-zstd-line read : ${parsed} parsed of ${sessions.length}, ${(bytesRead / 1e6).toFixed(1)} MB read   ${r(t2, t3)}`)
console.log(`stat per artifact    : ${stats}                       ${r(t3, t4)}`)
console.log(`TOTAL                : ${r(t0, t4)}  (one session/list scan, single-threaded, no engine work)`)
