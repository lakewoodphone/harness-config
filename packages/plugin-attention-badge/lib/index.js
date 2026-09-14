/**
 * dsh-plugin-attention-badge - the host half.
 *
 * There is deliberately almost nothing here. The badge itself is a browser concern: a script
 * tag and a fixed-position overlay, both of which `lib/client.js` owns. The host contributes no
 * service, no command and no tool, because it has nothing to add - the findings are read over
 * HTTP by the badge, from the host that publishes them.
 *
 * Its whole job is to be a valid Cordis plugin so the row activates and the client bundle is
 * mounted with it. A row that mounts and contributes nothing is a bug; a row that mounts and
 * contributes exactly one script tag is this package's entire contract.
 */

const name = 'attention-badge';

function apply() {
  // Nothing to wire. See the module comment: a host half that invented a service here would be
  // the asymmetry this package exists to remove.
}

export { name, apply };
