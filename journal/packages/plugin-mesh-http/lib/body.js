/**
 * Bounded request intake: read exactly the bytes the caller sent, never more than allowed.
 *
 * WHY THE RAW BYTES AND NOT A PARSED OBJECT
 * The signature covers the exact body bytes, so anything that re-encodes them (a JSON
 * round-trip, a normalising parser, a charset conversion) verifies a DIFFERENT message than
 * the one that arrived. The body is therefore read as bytes, verified as bytes, and only then
 * decoded and parsed. `dsh-webhook-github` does the same thing for the same reason
 * (`NM/dsh-webhook-github/lib/index.js:33-61` is the shipped version of this function).
 *
 * WHY THE CEILING IS IN BYTES AND NOT CHARACTERS
 * A `Content-Length` of 1 GiB of 'a' is 1 GiB of memory if it is read first and measured
 * later. The ceiling is checked twice: against the declared length before a single byte is
 * consumed, and against the running total while reading, so a caller that lies about its
 * length is cut off by the second check and a caller that is honest is refused by the first.
 * Both answer 413 and then `resume()` the stream, because an unconsumed body on a kept-alive
 * connection is the next request's prefix.
 */

/** One request refusal whose message is safe to return without echoing request data. */
export class IntakeError extends Error {
  constructor(status, reason, detail) {
    super(detail === undefined ? reason : `${reason}: ${detail}`);
    this.name = 'IntakeError';
    this.status = status;
    this.reason = reason;
    this.detail = detail;
  }
}

/** Parse a decimal `Content-Length`, or reject an ambiguous header. */
export function contentLength(headers) {
  const value = headers['content-length'];
  if (value === undefined) return undefined;
  if (!/^(0|[1-9]\d*)$/.test(value)) throw new IntakeError(400, 'invalid-content-length');
  const length = Number(value);
  if (!Number.isSafeInteger(length)) throw new IntakeError(413, 'content-length-too-large');
  return length;
}

/**
 * Read one request body as raw bytes, bounded.
 *
 * @param {import('node:http').IncomingMessage & {readableEnded?: boolean}} request
 * @param {number} maxBodyBytes
 * @returns {Promise<Buffer>}
 * @throws {IntakeError}
 */
export async function readBoundedBody(request, maxBodyBytes) {
  const declared = contentLength(request.headers);
  if (declared !== undefined && declared > maxBodyBytes) {
    request.resume();
    throw new IntakeError(413, 'body-too-large', `declared ${declared} > ${maxBodyBytes}`);
  }
  const chunks = [];
  let size = 0;
  try {
    for await (const raw of request) {
      const chunk = Buffer.isBuffer(raw) ? raw : Buffer.from(raw);
      size += chunk.byteLength;
      if (size > maxBodyBytes) {
        request.resume();
        throw new IntakeError(413, 'body-too-large', `${size} > ${maxBodyBytes}`);
      }
      chunks.push(chunk);
    }
  } catch (error) {
    if (error instanceof IntakeError) throw error;
    throw new IntakeError(400, 'body-aborted');
  }
  if (!request.complete && request.readableEnded !== true) throw new IntakeError(400, 'body-aborted');
  return Buffer.concat(chunks, size);
}

/** Whether `content-type` names JSON with at most one UTF-8 charset parameter. */
export function isJsonContentType(value) {
  if (value === undefined) return false;
  const [mediaType, parameter, ...extra] = String(value).split(';').map((part) => part.trim());
  if (mediaType?.toLowerCase() !== 'application/json') return false;
  if (parameter === undefined) return true;
  return extra.length === 0 && /^charset=(?:utf-8|"utf-8")$/i.test(parameter);
}

/** Decode a body that has already been verified, and parse it as a JSON object. */
export function parseJsonObject(bytes) {
  let text;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    throw new IntakeError(400, 'body-not-utf8');
  }
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new IntakeError(400, 'body-not-json');
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new IntakeError(400, 'body-not-an-object');
  }
  return parsed;
}
