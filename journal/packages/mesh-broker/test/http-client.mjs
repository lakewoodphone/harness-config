/**
 * A tiny HTTP client for the tests.
 *
 * `fetch` would do, but on the authority's Node v20.20.2 it still announces itself as an
 * experimental feature on first use, and test output that opens with a warning nobody can
 * act on trains people to ignore test output. This is 40 lines, uses node:http, and gives
 * the raw status and the parsed body - which is what the "zero non-200 responses" assertion
 * needs anyway.
 */

import http from 'node:http';

export function requestJson(url, { method = 'GET', body = undefined, headers = {}, timeoutMs = 10_000 } = {}) {
  const payload = body === undefined ? null : (typeof body === 'string' ? body : JSON.stringify(body));
  const target = new URL(url);
  return new Promise((resolve, reject) => {
    const request = http.request({
      method,
      hostname: target.hostname,
      port: target.port,
      path: `${target.pathname}${target.search}`,
      headers: {
        accept: 'application/json',
        ...(payload === null ? {} : { 'content-type': 'application/json', 'content-length': Buffer.byteLength(payload) }),
        ...headers,
      },
    }, (response) => {
      const chunks = [];
      response.on('data', (chunk) => chunks.push(chunk));
      response.on('end', () => {
        const raw = Buffer.concat(chunks).toString('utf8');
        let json = null;
        let parseError = null;
        try {
          json = JSON.parse(raw);
        } catch (error) {
          parseError = error.message;
        }
        resolve({ status: response.statusCode ?? 0, json, raw, parseError, headers: response.headers });
      });
      response.on('error', reject);
    });
    request.setTimeout(timeoutMs, () => request.destroy(new Error(`test client timed out after ${timeoutMs} ms`)));
    request.on('error', reject);
    if (payload !== null) request.write(payload);
    request.end();
  });
}

export const postPlace = (baseUrl, task) => requestJson(`${baseUrl}/place`, { method: 'POST', body: { task } });
export const postDone = (baseUrl, body) => requestJson(`${baseUrl}/done`, { method: 'POST', body });
export const getNodes = (baseUrl, query = '') => requestJson(`${baseUrl}/nodes${query}`);

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
