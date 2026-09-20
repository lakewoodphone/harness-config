/**
 * dsh-plugin-session-link — the host half.
 *
 * It does nothing at runtime, on purpose, and for the same reason `dsh-plugin-mobile` does nothing:
 * the capability is browser behaviour (reading `location.hash` and selecting a session), and there
 * is no reason for the engine to gain a process, a route or a privilege to provide it. The row
 * exists because a bundle must be a real loader entry for its client half to be part of the browser
 * roster — see the measured note in `packages/plugin-mobile/lib/index.js`, which this file mirrors.
 *
 * The companion is `lib/client.js`. Why the fragment and not a path or a query parameter, and why
 * the phone gate is what makes a cold visit keep it, is documented there.
 */
const name = 'plugin-session-link';

function apply() {
  // no host-side behaviour
}

export { name, apply };
