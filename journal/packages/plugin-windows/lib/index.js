/**
 * dsh-plugin-windows — the host half.
 *
 * It does nothing at runtime, on purpose. The capability this package provides is the
 * `+` control in the browser half, and the work of opening a window belongs to the
 * launcher (`multi-window/dshw.ps1 new`) — not to a process spawned inside the engine.
 * Keeping the host row inert means:
 *
 *   - no engine-side privilege is needed to create a window;
 *   - the engine cannot be used as a general "run this process" pipe by a page;
 *   - `dshw new` remains the single implementation of "open one more window", so the
 *     `+` control, the desktop shortcut and the command line cannot drift apart.
 *
 * The row exists because a bundle must be a real loader entry for its client half to be
 * part of the browser roster.
 */
const name = 'plugin-windows';

function apply() {
  // no host-side behaviour
}

export { name, apply };
