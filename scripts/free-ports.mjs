// Free TCP ports for a throwaway MetaList's HTTP and HTTPS listeners.
//
// A port is free when the system hands it out for a probe that then closes, which leaves it
// free only until something else takes it. Runs started side by side (run-browser-suites.mjs)
// each probing for themselves could be handed the same ports, one run's HTTP port being the
// other's HTTPS port (GitHub, 2026-11-21: editable-embeds and ai-response-menu reached each
// other's servers and both failed). So the runner picks the ports of all its runs itself, one
// at a time, and never hands out a port twice; a run started on its own picks its own.

import {createServer} from 'node:net';

// The environment variables through which the runner gives a run its ports.
export const HTTP_PORT_VARIABLE = 'BROWSER_TEST_HTTP_PORT';
export const HTTPS_PORT_VARIABLE = 'BROWSER_TEST_HTTPS_PORT';

// A run's server listens on two ports: HTTP and HTTPS.
const PORTS_PER_RUN = 2;

async function probedFreePort() {
  const probe = createServer();
  await new Promise(resolve => probe.listen(0, '127.0.0.1', resolve));
  const freeTcpPort = probe.address().port;
  await new Promise(resolve => probe.close(resolve));
  return freeTcpPort;
}

/** Two free ports, {http, https}, none of them in `handedOut`, which gains both. */
export async function pickPortPair(handedOut) {
  if (!(handedOut instanceof Set)) throw new Error('pickPortPair needs the set of ports already handed out');
  const picked = [];
  while (picked.length < PORTS_PER_RUN) {
    const port = await probedFreePort();
    if (!handedOut.has(port)) {
      handedOut.add(port);
      picked.push(port);
    }
  }
  const [http, https] = picked;
  if (http === https) throw new Error(`pickPortPair picked port ${http} twice`);
  return {http, https};
}

function portFrom(environment, variable) {
  const text = environment[variable];
  if (!/^[1-9][0-9]*$/.test(text)) throw new Error(`${variable} must be a port number, not ${JSON.stringify(text)}`);
  return Number(text);
}

/**
 * The ports a run's server listens on: those the runner gave it, or, for a run started on its
 * own, two it picks. The runner gives both or neither.
 */
export async function portsForRun(environment) {
  const hasHttp = Object.hasOwn(environment, HTTP_PORT_VARIABLE);
  if (hasHttp !== Object.hasOwn(environment, HTTPS_PORT_VARIABLE)) {
    throw new Error(`${HTTP_PORT_VARIABLE} and ${HTTPS_PORT_VARIABLE} are given together or not at all`);
  }
  if (!hasHttp) return pickPortPair(new Set());
  const ports = {http: portFrom(environment, HTTP_PORT_VARIABLE), https: portFrom(environment, HTTPS_PORT_VARIABLE)};
  if (ports.http === ports.https) throw new Error(`${HTTP_PORT_VARIABLE} and ${HTTPS_PORT_VARIABLE} are both ${ports.http}`);
  return ports;
}
