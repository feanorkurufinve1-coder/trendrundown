// TrendRundown: сайт (готовые страницы из папки site) + счётчики смайликов под статьями.
// /api/react?p=t/<slug>        GET  → сколько раз нажат каждый смайлик
// /api/react  {p, e}           POST → голос (один на человека и статью; можно поменять)
import { DurableObject } from "cloudflare:workers";

const EMOJI = 10;                                   // сколько смайликов под статьёй
const PAGE_RE = /^[tx]\/[a-z0-9-]{1,90}$/;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

async function sha(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].slice(0, 12).map(b => b.toString(16).padStart(2, "0")).join("");
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/api/react") {
      return env.ASSETS.fetch(request);
    }
    if (request.method === "GET") {
      const p = url.searchParams.get("p") || "";
      if (!PAGE_RE.test(p)) return json({ error: "bad page" }, 400);
      const stub = env.REACTIONS.get(env.REACTIONS.idFromName(p));
      return json(await stub.counts());
    }
    if (request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "bad json" }, 400); }
      const p = String(body.p || ""), e = Number(body.e);
      if (!PAGE_RE.test(p) || !Number.isInteger(e) || e < 0 || e >= EMOJI) return json({ error: "bad vote" }, 400);
      const ip = request.headers.get("cf-connecting-ip") || "0";
      const ua = request.headers.get("user-agent") || "";
      if (/bot|crawl|spider|slurp|preview/i.test(ua)) return json({ error: "bots do not vote" }, 403);
      const voter = await sha(ip + "|" + ua + "|" + p);      // один голос с одного устройства на статью
      const stub = env.REACTIONS.get(env.REACTIONS.idFromName(p));
      return json(await stub.vote(voter, e));
    }
    return json({ error: "method" }, 405);
  },
};

export class Reactions extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
  }
  async counts() {
    const c = (await this.ctx.storage.get("counts")) || new Array(EMOJI).fill(0);
    return { counts: c };
  }
  async vote(voter, e) {
    const s = this.ctx.storage;
    const c = (await s.get("counts")) || new Array(EMOJI).fill(0);
    const prev = await s.get("v:" + voter);
    if (prev === e) return { counts: c, mine: e };
    if (prev !== undefined && c[prev] > 0) c[prev] -= 1;
    c[e] += 1;
    await s.put({ counts: c, ["v:" + voter]: e });
    return { counts: c, mine: e };
  }
}
