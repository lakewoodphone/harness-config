/**
 * DeepSeek pass-through proxy for machines behind a URL-category filter.
 *
 * WHY THIS EXISTS
 * Yocheved's laptop sits behind Techloq, which intercepts TLS and blocks `api.deepseek.com` by URL
 * category. The block is answered with an HTML page carrying a SUCCESS status, so her harness cannot
 * even tell it was blocked. Measured 2026-09-14 from a neutral network, the direct DeepSeek route is
 * also dramatically faster than the alternative she was on (747 ms vs 1,693 ms to first token,
 * 160 vs 24 tokens/s), so routing her around the block is worth real money and time.
 *
 * WHAT IT DOES
 * Terminates TLS on a hostname that the filter already allows (*.abletelsolutions.com, proven by her
 * box reaching other hostnames on that zone), then makes the upstream call itself from Cloudflare's
 * edge, where the filter has no visibility. The model stream is passed through unbuffered.
 *
 * WHAT IT IS NOT
 * It is not a general-purpose open proxy. The caller must present a bearer token, and the Worker
 * verifies it against the upstream by asking DeepSeek for the model list. An unknown token is
 * rejected here rather than being forwarded, so the hostname cannot be used to reach DeepSeek by
 * anything that does not already hold a valid key.
 *
 * The model key is NOT stored in this Worker: the caller supplies it, exactly as it would to
 * DeepSeek directly, and this forwards it. That keeps the key's blast radius identical to calling
 * DeepSeek directly, and means rotating the key needs no redeploy here.
 */

const UPSTREAM = 'https://api.deepseek.com';

// Verification cache: a bearer token is checked once per TTL rather than on every request, so a
// streaming chat call costs one extra upstream round trip at most every few minutes. Invalid tokens
// are cached too, so a bad actor cannot turn this into a request amplifier.
const TOKEN_TTL_MS = 10 * 60 * 1000;
const verified = new Map(); // token -> { ok: boolean, at: number }

async function isAuthorized(authHeader) {
  if (!authHeader || !authHeader.startsWith('Bearer ')) return false;
  const token = authHeader.slice(7).trim();
  if (!token) return false;

  const hit = verified.get(token);
  const now = Date.now();
  if (hit && now - hit.at < TOKEN_TTL_MS) return hit.ok;

  let ok = false;
  try {
    const res = await fetch(`${UPSTREAM}/v1/models`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    ok = res.ok;
  } catch {
    ok = false;
  }
  verified.set(token, { ok, at: now });
  // Bound the map: it only ever holds tokens that have been presented here.
  if (verified.size > 50) {
    for (const [k, v] of verified) {
      if (now - v.at > TOKEN_TTL_MS) verified.delete(k);
    }
  }
  return ok;
}

export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }
    if (url.pathname === '/__health') {
      return json({ ok: true, upstream: UPSTREAM, service: 'deepseek-proxy' });
    }

    if (!(await isAuthorized(request.headers.get('authorization')))) {
      return json({ error: { message: 'unauthorized: a valid bearer token is required', type: 'proxy_auth' } }, 401);
    }

    // Forward the path and query unchanged, so /v1/chat/completions, /v1/models and anything else
    // DeepSeek exposes all work without this file knowing about them.
    const target = UPSTREAM + url.pathname + url.search;

    const headers = new Headers(request.headers);
    headers.delete('host');
    headers.delete('cf-connecting-ip');
    headers.delete('cf-ray');
    headers.delete('x-forwarded-for');
    headers.delete('x-forwarded-proto');
    // Accept-Encoding is left alone: the upstream negotiation is between this Worker and DeepSeek.

    const init = { method: request.method, headers, redirect: 'manual' };
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      init.body = request.body;
    }

    let upstream;
    try {
      upstream = await fetch(target, init);
    } catch (e) {
      return json({ error: { message: `proxy could not reach upstream: ${String(e && e.message)}`, type: 'proxy_upstream' } }, 502);
    }

    // STREAMING IS THE POINT. The body is handed straight through: for an SSE chat completion this
    // returns as soon as the upstream sends its first chunk and keeps flowing, instead of buffering
    // the whole answer and destroying the perceived speed that motivated this proxy. No
    // content-length is set, because the length is not known until the model stops.
    const out = new Headers(upstream.headers);
    out.delete('content-length');
    out.delete('content-encoding'); // the runtime decodes; re-encoding would corrupt SSE framing
    out.set('Cache-Control', 'no-store');
    for (const [k, v] of Object.entries(corsHeaders())) out.set(k, v);

    return new Response(upstream.body, { status: upstream.status, statusText: upstream.statusText, headers: out });
  },
};

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
  };
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}
