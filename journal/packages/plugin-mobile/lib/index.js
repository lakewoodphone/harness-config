/**
 * dsh-plugin-mobile — the host half.
 *
 * It does nothing at runtime, on purpose, and for the same reason `dsh-plugin-windows`
 * does nothing: the capability is browser behaviour, and there is no reason for the engine
 * to gain a process, a route, or a privilege to provide it. The row exists because a bundle
 * must be a real loader entry for its client half to be part of the browser roster.
 *
 * The companion to this file is `lib/client.js` on the phone and `assets/mobile.css`
 * injected by `scripts/phone-gate.py`. The split is deliberate:
 *
 *   - what CSS can express (touch targets, the iOS zoom trigger, safe areas, the open
 *     drawer overlaying instead of squeezing) lives in the stylesheet, because it must also
 *     reach a browser that has no plugin installed;
 *   - what needs state — closing the drawer once a conversation has actually been picked —
 *     lives here, because a stylesheet cannot see a selection.
 */
const name = 'plugin-mobile';

function apply() {
  // no host-side behaviour
}

export { name, apply };
