/* Video library download helper (service worker).
   The page hands over a decryption key and a file; the browser then downloads /videos/dl/<token>/<name>
   as a normal download, while this worker fetches the encrypted file and decrypts it piece by piece
   (videos are stored in 4 MB pieces), so the browser's own download manager shows the progress. */
const jobs = new Map();
const MAGIC = [89, 84, 86, 67, 49];                       // "YTVC1"

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

self.addEventListener("message", e => {
  const d = e.data || {};
  if (d.type === "download") {
    jobs.set(d.token, d);
    setTimeout(() => jobs.delete(d.token), 10 * 60 * 1000);
    e.ports[0] && e.ports[0].postMessage("ok");
  }
});

self.addEventListener("fetch", e => {
  const m = new URL(e.request.url).pathname.match(/\/dl\/([A-Za-z0-9]+)\//);
  if (!m) return;
  const job = jobs.get(m[1]);
  e.respondWith(job ? serve(job) : new Response("This download link has expired. Go back and tap Download again.",
                                                  {status: 404, headers: {"Content-Type": "text/plain"}}));
});

function aad(i, n){
  const a = new Uint8Array(8), v = new DataView(a.buffer);
  v.setUint32(0, i); v.setUint32(4, n);
  return a;
}

// read exactly `n` bytes (or what's left) from a stream reader, without quadratic copying
function byteReader(reader){
  let parts = [], have = 0, done = false;
  return async n => {
    while (have < n && !done) {
      const r = await reader.read();
      if (r.done) { done = true; break; }
      parts.push(r.value); have += r.value.length;
    }
    const take = Math.min(n, have), out = new Uint8Array(take);
    let off = 0;
    while (off < take) {
      const p = parts[0], k = Math.min(p.length, take - off);
      out.set(p.subarray(0, k), off); off += k;
      if (k === p.length) parts.shift(); else parts[0] = p.subarray(k);
    }
    have -= take;
    return out;
  };
}

async function serve(job){
  const r = await fetch(job.url, {cache: "no-store"});
  if (!r.ok) return new Response("File not found (" + r.status + ")", {status: 502});
  const total = Number(r.headers.get("content-length")) || 0;
  const read = byteReader(r.body.getReader());
  const head = await read(9);
  const name = encodeURIComponent(job.name).replace(/['()]/g, escape);
  const headers = {"Content-Type": job.mime || "application/octet-stream",
                   "Content-Disposition": `attachment; filename*=UTF-8''${name}`};
  if (!MAGIC.every((c, i) => head[i] === c)) {             // small single-piece file
    const rest = await read(1 << 30), all = new Uint8Array(head.length + rest.length);
    all.set(head); all.set(rest, head.length);
    const plain = await crypto.subtle.decrypt({name: "AES-GCM", iv: all.slice(0, 12)}, job.key, all.subarray(12));
    return new Response(plain, {headers});
  }
  const size = new DataView(head.buffer).getUint32(5), step = 12 + size + 16;
  const n = total ? Math.max(1, Math.ceil((total - 9) / step)) : 0;
  if (total) headers["Content-Length"] = String(total - 9 - n * 28);
  let i = 0;
  const body = new ReadableStream({
    async pull(ctl){
      const piece = await read(step);
      if (!piece.length) { ctl.close(); return; }
      try {
        const plain = await crypto.subtle.decrypt({name: "AES-GCM", iv: piece.slice(0, 12), additionalData: aad(i, n)},
                                                  job.key, piece.subarray(12));
        ctl.enqueue(new Uint8Array(plain)); i++;
        if (i === n) ctl.close();
      } catch (err) { ctl.error(err); }
    }
  });
  return new Response(body, {headers});
}
