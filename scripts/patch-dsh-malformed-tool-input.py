#!/usr/bin/env python3
"""Patch the pinned DSH runtime so one malformed tool call cannot kill a whole turn.

THE DEFECT (found 2026-10-05, root cause read out of the source and out of the owner's own
session ledger, not guessed)

`@deepseek-ai/dsh-llm-deepseek/lib/index.js` validates every tool-call block at `message_stop`
with a bare `JSON.parse(content.arguments)` and throws on failure:

    } catch (_invalidProviderToolJson) {
        return malformed("tool input is invalid JSON");
    }

`malformed()` throws `LlmError(..., "MALFORMED_RESPONSE")`; the agent loop turns a thrown request
failure into `turn/end {kind:error}` -- THE WHOLE TURN DIES, every tool call in it is discarded, and
the owner has to restate the request. He did, four times today:

  session-8bd84e58 turn 9  step 3   mcp__jina__search_web   `{"num": 5, "query": "6,825,420" patent switch}`
  session-4c3ded25 turn 88 step 6   mcp__jina__read_url     `{"url": https://davkawriter.com/products/..., "question": "..."}`
  session-4c3ded25 turn 96 step 1   mcp__jina__search_web   `{"query": "iPod Nano 7" screen replacement ..., "num": 6}`
  + `"you did somehting wrong"` / `"you did something wrong"` as the next user message

Corpus measurement, every session log this machine has kept for 30 days
(`harness-config/dsh-update/tests/tool-input-repair.test.mjs` reads it):
**86 malformed tool-call argument sets** across `write` (12), `edit` (5), `send_message` (7),
`read` (2), `pwsh` (6), `web_search` (3), `subagent` (1), `mcp__jina__*` (25),
`mcp__firecrawl__firecrawl_scrape` (22). Four shapes, every one of them ONE corruption away from
valid JSON:

  1. an object value emitted as a bare token   `{"url": https://example.com/a, ...}`   (14/86)
  2. a bracket/brace the model never closed    `{"queries": ["a", "b"], "c"]}`          (20/86)
  3. a quote inside a string left unescaped    `{"query": "iPod Nano 7" screen ..."}`
  4. a value cut off mid-string by the model   `{"content": "...and then the pho`

WHAT THIS PATCH CHANGES (two edits, both idempotent)

  1. add a `repairToolInput(raw)` function next to `object()`. It tries the strict parse first and
     returns unchanged when the JSON is already valid. Otherwise it may only ADD syntactic
     characters (quote, backslash, comma, bracket) -- it never deletes, truncates, reorders or
     invents content, and that is checked, not asserted: every byte of the original must survive
     into the repair in order. A repair that would need invented content is refused.
  2. the validation loop calls it. Strict-valid input is untouched. A repaired input is used and
     reported to the runtime log. An unrepairable input becomes `{}`, which the tool layer answers
     with its own `invalid arguments: ...` tool result that the MODEL can read and correct inside
     the same turn -- measured in `dsh-tools/lib/index.js:812` (`InvalidToolArgumentsError`,
     code INVALID_ARGUMENTS) and `:823` (`validateToolArguments`). Either way the turn survives.

Why `{}` is the right last resort rather than a guess: a wrong-but-plausible `write`/`edit`/
`send_message` argument would silently do the wrong thing, and this seat has already sent one
outbound message the owner never approved. An empty argument set does nothing at all, and the model
sees why.

WHY A PATCH AND NOT A VERSION BUMP

0.2.0-rc.2 is the newest published `dsh-llm-deepseek` (`0.2.1-alpha.1` is byte-identical --
sha256 226e2047b843f954..., checked 2026-10-05), so there is nothing to upgrade to. Upgrading the
runtime is a change to every running agent session and is not this script's call.

USAGE
    python patch-dsh-malformed-tool-input.py            # patch (idempotent)
    python patch-dsh-malformed-tool-input.py --check    # exit 1 if not patched
    python patch-dsh-malformed-tool-input.py --root DIR # a different @deepseek-ai runtime root

Exit codes: 0 patched or already-patched; 1 nothing was patched and something is wrong (missing
anchor, unpatched under --check). It never edits a file it could not first read and anchor.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from pathlib import Path

SENTINEL = "MESHFIX:malformed-tool-input"

# The standalone source of the repair engine. `tests/tool-input-repair.test.mjs` imports THIS
# string, runs it against the captured 86-case corpus, and so tests the code that ships rather
# than a copy of it. Deliberately dependency-free and self-contained.
REPAIR_SOURCE = r'''
/** Repair model-authored tool-call JSON that is not valid JSON. MESHFIX:malformed-tool-input */
function repairToolInput(raw) {
	if (typeof raw !== "string") return {
		ok: false,
		error: "not a string",
		repair: null
	};
	const strict = tryParseToolJson(raw);
	if (strict.ok) return {
		ok: true,
		value: strict.value,
		repair: null,
		added: 0
	};
	for (const [name, fix] of TOOL_INPUT_REPAIRS) {
		const candidate = fix(raw);
		if (candidate === null || candidate === raw) continue;
		const parsed = tryParseToolJson(candidate);
		if (!parsed.ok) continue;
		if (parsed.value === null || typeof parsed.value !== "object" || Array.isArray(parsed.value)) continue;
		if (!preservesToolInputContent(raw, candidate)) continue;
		return {
			ok: true,
			value: parsed.value,
			repair: name,
			added: candidate.length - raw.length
		};
	}
	return {
		ok: false,
		error: strict.error,
		repair: null
	};
}
function tryParseToolJson(text) {
	try {
		return {
			ok: true,
			value: JSON.parse(text)
		};
	} catch (error) {
		return {
			ok: false,
			error: String(error && error.message ? error.message : error)
		};
	}
}
/** Every byte of the original must survive: a repair may add syntax, never rewrite content. */
function preservesToolInputContent(original, repaired) {
	let i = 0;
	for (const ch of repaired) {
		if (i < original.length && ch === original[i]) i += 1;
		else if (!"\\\",[]{}".includes(ch)) return false;
	}
	return i === original.length;
}
/** A bare token that can only have been meant as a string value (a URL, a path, a word). */
const TOOL_INPUT_BARE_TOKEN = /"([A-Za-z_][A-Za-z0-9_.-]*)"(\s*:\s*)([^\s"{}[\],][^\s{}\[\],]*)/gu;
/** A quote that opened a string was doubled by the model. */
const TOOL_INPUT_EXTRA_QUOTE = /"(\\+)(?=")/gu;
/** Append only the closers the document is missing. Refuses an open string (that needs content). */
function closeToolInputStructures(text) {
	const stack = [];
	let inString = false;
	let escaped = false;
	let last = "";
	let lastIndex = -1;
	for (let i = 0; i < text.length; i += 1) {
		const ch = text[i];
		if (inString) {
			if (escaped) escaped = false;
			else if (ch === "\\") escaped = true;
			else if (ch === "\"") inString = false;
			continue;
		}
		if (ch === "\"") {
			inString = true;
			continue;
		}
		if (ch === "{" || ch === "[") stack.push(ch === "{" ? "}" : "]");
		else if (ch === "}" || ch === "]") {
			if (stack.length === 0 || stack[stack.length - 1] !== ch) return null;
			stack.pop();
		}
		if (!/\s/u.test(ch)) {
			last = ch;
			lastIndex = i;
		}
	}
	if (inString) return null;
	if (stack.length === 0) return null;
	let out = text;
	if (last === ",") out = out.slice(0, lastIndex);
	if (last === ":") return null;
	return out + stack.reverse().join("");
}
const TOOL_INPUT_REPAIRS = [
	["bare-token-quoted", (text) => text.replace(TOOL_INPUT_BARE_TOKEN, "\"$1\"$2\"$3\"")],
	["extra-quote-removed", (text) => text.replace(TOOL_INPUT_EXTRA_QUOTE, (_m, backslashes) => backslashes.slice(1) + "\"")],
	["close-structures", (text) => closeToolInputStructures(text)]
];
'''

OBJECT_ANCHOR = """/** Reject malformed JSON objects at provider and durable-data reads.
* @param value - untrusted decoded JSON.
* @param code - owning failure category.
* @returns the validated object.
*/
function object(value, code = "MALFORMED_RESPONSE") {
	if (typeof value !== "object" || value === null || Array.isArray(value)) throw new LlmError("DeepSeek Messages expected a JSON object", code);
	return value;
}"""

OBJECT_PATCHED = OBJECT_ANCHOR + "\n" + REPAIR_SOURCE.strip("\n")

VALIDATE_ANCHOR = """			if (reason.kind !== "max-tokens") for (const { content } of blocks.values()) {
				if (content.type !== "tool-call") continue;
				let parsed;
				try {
					parsed = JSON.parse(content.arguments);
				} catch (_invalidProviderToolJson) {
					return malformed("tool input is invalid JSON");
				}
				object(parsed);
			}"""

VALIDATE_PATCHED = """			if (reason.kind !== "max-tokens") for (const { content } of blocks.values()) {
				if (content.type !== "tool-call") continue;
				/* MESHFIX:malformed-tool-input — the arguments were already settled at `block-end`, so a
				parse failure here can only come from a shape the block-end edit did not cover; it is kept
				as a hard failure deliberately, so this fix can never silently accept unparseable input. */
				let parsed;
				try {
					parsed = JSON.parse(content.arguments);
				} catch (_invalidProviderToolJson) {
					return malformed("tool input is invalid JSON");
				}
				object(parsed);
			}"""

# ── edit 3: settle the tool arguments, then emit the block ───────────────────────────────────
# This is the edit that matters, and its shape is forced by the harness. The harness's
# AssistantStreamAccumulator.push() deep-copies the chunk into JSON at the moment it is pushed
# (`snapshotChunk`), and `blocks()`/`message()` are built from those copies -- so mutating the block
# after yielding it changes nothing that survives. The first version of this patch repaired at
# `block-end` and *then* yielded, and measured on the real corpus all 86 cases "finished cleanly"
# while all 86 still handed the tool unparseable arguments. The block must therefore be EMITTED
# after the arguments are settled, which means the emit moves into a helper that the settled path
# calls.
BLOCKEND_ANCHOR = """			} else {
				block.closed = true;
				if (block.content.type === "tool-call" && block.json.length > 0) block.content.arguments = block.json;
				yield {
					type: "block-end",
					index: block.index,
					block: { ...block.content }
				};
			}
		} else if (event.type === "message_delta") {"""

BLOCKEND_PATCHED = """			} else {
				block.closed = true;
				if (block.content.type === "tool-call" && block.json.length > 0) block.content.arguments = block.json;
				/* MESHFIX:malformed-tool-input — settle the tool arguments BEFORE the block is emitted,
				because the harness deep-copies this chunk into JSON at the moment it is pushed and every
				later read is served from that copy. A strict parse first (unchanged behaviour); only when
				the model emitted one corruption away from valid JSON is a repair attempted, and a repair
				may only add syntax characters -- every byte of the raw text must survive into the repair
				in order, so no content can be invented or dropped. Unrepairable input becomes `{}`, and
				the tool layer answers with its own `invalid arguments: ...` result that the model can read
				and correct inside the same turn. Before this, EITHER case threw MALFORMED_RESPONSE and
				killed the whole turn -- 86 occurrences in the 30 days of session ledger this machine
				kept, four of them on 2026-10-05. */
				if (block.content.type === "tool-call") {
					let settled;
					try {
						settled = JSON.parse(block.content.arguments);
					} catch (_invalidProviderToolJson) {
						settled = void 0;
					}
					if (settled === void 0) {
						const repaired = repairToolInput(block.content.arguments);
						const raw = block.content.arguments;
						if (repaired.ok) {
							block.content.arguments = JSON.stringify(repaired.value);
							if (repaired.repair !== null) onMalformedToolInput({
								kind: "repaired",
								tool: block.content.name,
								repair: repaired.repair,
								added: repaired.added,
								raw
							});
						} else {
							block.content.arguments = "{}";
							onMalformedToolInput({
								kind: "emptied",
								tool: block.content.name,
								error: repaired.error,
								raw
							});
						}
					}
				}
				yield emitToolInput(block);
			}
		} else if (event.type === "message_delta") {"""

# The helper the settled path emits through. It runs at `yield` time, so the chunk it produces is
# the one that gets deep-copied -- which is the whole point.
HELPER_ANCHOR = """function deltaChunk(block, raw) {"""

HELPER_PATCHED = """/** The `block-end` chunk for one closed block. MESHFIX:malformed-tool-input
* @param block - closed accumulating block.
* @returns the chunk the harness copies into the durable assistant message.
*/
function emitToolInput(block) {
	return {
		type: "block-end",
		index: block.index,
		block: { ...block.content }
	};
}
function deltaChunk(block, raw) {"""

# One warning per (kind, tool, shape) per process, so a repeating fault is visible without a flood.
REPORTER_SOURCE = r'''
/** One warning per distinct malformed-tool-input shape per process. MESHFIX:malformed-tool-input */
const REPORTED_MALFORMED_TOOL_INPUT = /* @__PURE__ */ new Set();
function onMalformedToolInput(report) {
	const signature = `${report.kind}:${report.tool}:${String(report.raw).slice(0, 64)}`;
	if (REPORTED_MALFORMED_TOOL_INPUT.has(signature)) return;
	REPORTED_MALFORMED_TOOL_INPUT.add(signature);
	const head = typeof report.raw === "string" ? report.raw.slice(0, 400) : "";
	try {
		process.stderr.write(`MESHFIX:malformed-tool-input ${JSON.stringify({
			kind: report.kind,
			tool: report.tool,
			repair: report.repair ?? null,
			error: report.error ?? null,
			added: report.added ?? null,
			chars: typeof report.raw === "string" ? report.raw.length : null,
			head
		})}\n`);
	} catch (_logFailed) {}
}
'''

REPORTER_ANCHOR = """function malformed(detail) {
	throw new LlmError(`DeepSeek Messages stream: ${detail}`, "MALFORMED_RESPONSE");
}"""

REPORTER_PATCHED = REPORTER_SOURCE.strip("\n") + "\n" + REPORTER_ANCHOR

EDITS = (
    (OBJECT_ANCHOR, OBJECT_PATCHED),
    (HELPER_ANCHOR, HELPER_PATCHED),
    (REPORTER_ANCHOR, REPORTER_PATCHED),
    (BLOCKEND_ANCHOR, BLOCKEND_PATCHED),
)
TARGET = "dsh-llm-deepseek/lib/index.js"


def sha8(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _extract_function(text: str, name: str) -> str:
    """Pull one top-level function declaration (and its body) out of an installed adapter."""
    import re as _re

    match = _re.search(rf"^(?:async )?function\*? {_re.escape(name)}\(", text, _re.MULTILINE)
    if match is None:
        raise SystemExit(f"FAIL: cannot find function {name} in the installed adapter")
    start = match.start()
    open_brace = text.index("{", start)
    depth = 0
    for i in range(open_brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise SystemExit(f"FAIL: unbalanced braces while extracting {name}")


def extract_translate_module(text: str) -> str:
    """Build a standalone module around the installed, patched translate()."""
    repair_start = text.index("/** Repair model-authored tool-call JSON that is not valid JSON.")
    repair_end = text.index("];", text.index("const TOOL_INPUT_REPAIRS = [")) + 2
    report_start = text.index("/** One warning per distinct malformed-tool-input shape per process.")
    report_end = text.index("function malformed(detail)")
    parts = [
        "class LlmError extends Error { constructor(message, code, extra) { super(message); this.code = code; Object.assign(this, extra ?? {}); } }",
        "const ToolCallId = (value) => value;",
        text[repair_start:repair_end],
        text[report_start:report_end],
    ]
    for name in ("object", "string", "malformed", "indexOf", "updateUsage", "emitToolInput", "startBlock", "deltaChunk", "stopReason", "replayState"):
        parts.append(_extract_function(text, name))
    parts.append(_extract_function(text, "translate").replace("async function* translate(", "async function* translate(", 1))
    parts.append("export { translate };")
    return "\n".join(parts)


def candidate_roots() -> list[Path]:
    """Every place this runtime could be installed, in preference order.

    Mirrors `patch-dsh-settlement-crash.py`: a patch that only covers the machine it was written
    on is not a fix. Measured 2026-09-30 on the mesh worker, children run from
    `/home/zabz/dsh-engine/node_modules/@deepseek-ai`, which an npx-only search never finds.
    """
    roots: list[Path] = []
    env = os.environ.get("MESHFIX_DSH_ROOT")
    if env:
        roots.append(Path(env))
    home = Path.home()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        npx = Path(local) / "npm-cache" / "_npx"
        if npx.is_dir():
            roots.extend(sorted(p / "node_modules" / "@deepseek-ai" for p in npx.iterdir() if (p / "node_modules" / "@deepseek-ai").is_dir()))
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata) / "npm" / "node_modules" / "@deepseek-ai")
    for rel in (
        "dsh-engine/node_modules/@deepseek-ai",
        "code/dsh-engine/node_modules/@deepseek-ai",
        ".dsh/node_modules/@deepseek-ai",
        "code/deepseek-harness/node_modules/@deepseek-ai",
        "deepseek-harness/node_modules/@deepseek-ai",
        "node_modules/@deepseek-ai",
    ):
        roots.append(home / rel)
    # The pinned upgrade layouts: `harness-config/dsh-update/vendor/prefix/<version>/node_modules/
    # @deepseek-ai` is the tree the LIVE engine runs from on the Windows machines (measured
    # 2026-10-05: PID 21072 ran `.../vendor/prefix/0.2.0-rc.2/node_modules/@deepseek-ai/dsh/lib/
    # bin.js`), and it is not under any of the paths above.
    vendor = home / "code" / "harness-config" / "dsh-update" / "vendor" / "prefix"
    if vendor.is_dir():
        roots.extend(sorted(p / "node_modules" / "@deepseek-ai" for p in vendor.iterdir() if (p / "node_modules" / "@deepseek-ai").is_dir()))
    roots.extend(
        [
            Path("/usr/lib/node_modules/@deepseek-ai"),
            Path("/usr/local/lib/node_modules/@deepseek-ai"),
            Path("/opt/dsh-engine/node_modules/@deepseek-ai"),
        ]
    )
    seen, out = set(), []
    for r in roots:
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        if r.is_dir():
            out.append(r)
    return out


def apply(path: Path, check: bool) -> str:
    text = path.read_text(encoding="utf-8")
    if SENTINEL in text and all(new in text for _, new in EDITS):
        return "already-patched"
    if check:
        return "MISSING-PATCH"
    applied = 0
    for old, new in EDITS:
        if new in text:
            applied += 1
            continue
        if old not in text:
            raise SystemExit(
                f"FAIL {path}: the anchor this patch targets is not present.\n"
                f"  The runtime changed underneath the patch — do NOT hand-edit it.\n"
                f"  Re-derive the patch against this version instead.\n"
                f"  missing anchor begins: {old.splitlines()[0][:90]!r}"
            )
        if text.count(old) != 1:
            raise SystemExit(f"FAIL {path}: the anchor appears {text.count(old)} times, expected exactly 1")
        text = text.replace(old, new, 1)
        applied += 1
    backup = path.with_suffix(path.suffix + ".meshfix-bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(text, encoding="utf-8")
    return f"patched({applied})"


def main() -> int:
    ap = argparse.ArgumentParser(description="Patch the DSH runtime so a malformed tool call cannot kill a turn.")
    ap.add_argument("--check", action="store_true", help="verify the patch is present; exit 1 if not")
    ap.add_argument("--root", help="the @deepseek-ai runtime root to patch (default: every one found)")
    ap.add_argument("--emit-repair-source", help="write the embedded repair engine here (test harness use)")
    ap.add_argument("--emit-translate-source", help="write the installed patched translate() as a module (test harness use)")
    args = ap.parse_args()

    if args.emit_repair_source:
        Path(args.emit_repair_source).write_text(
            REPAIR_SOURCE + "\nexport { repairToolInput, tryParseToolJson, preservesToolInputContent };\n",
            encoding="utf-8",
        )
        print(f"wrote {args.emit_repair_source}")
        return 0
    if args.emit_translate_source:
        # The test harness runs the SHIPPED stream: the helper, the reporter and the block-end
        # settling code, extracted verbatim from the installed file, with only the adapter's outer
        # dependencies stubbed. That is what makes the regression test able to catch a fix that
        # "finishes cleanly" while still handing the tool unparseable arguments.
        target = (Path(args.root) if args.root else (candidate_roots() or [None])[0])
        if target is None:
            print("FAIL: no runtime root to read the patched adapter from")
            return 1
        file = target / TARGET
        text = file.read_text(encoding="utf-8")
        if SENTINEL not in text:
            print(f"FAIL: {file} is not patched")
            return 1
        Path(args.emit_translate_source).write_text(extract_translate_module(text), encoding="utf-8")
        print(f"wrote {args.emit_translate_source}")
        return 0

    roots = [Path(args.root)] if args.root else candidate_roots()
    if not roots:
        print("FAIL: no @deepseek-ai runtime root found. Set MESHFIX_DSH_ROOT or pass --root.")
        return 1

    verdict = 0
    for root in roots:
        print(f"=== runtime root: {root}")
        path = root / TARGET
        if not path.is_file():
            print(f"  {TARGET:44s} absent — nothing to patch")
            continue
        try:
            status = apply(path, args.check)
        except SystemExit as exc:
            print(f"  {TARGET:44s} {exc}")
            verdict = 1
            continue
        marker = "ok " if not status.startswith(("MISSING", "no-")) else "!! "
        print(f"  {marker}{TARGET:44s} {status}  sha8={sha8(path)}")
        if status in ("MISSING-PATCH", "no-anchor-applicable"):
            verdict = 1

    if args.check:
        print("PATCHED and verified" if verdict == 0 else "NOT PATCHED — a malformed tool call can still kill a whole turn")
    return verdict


if __name__ == "__main__":
    sys.exit(main())
