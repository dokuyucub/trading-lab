// Dis baslatici testleri: `node --test infra/shadow-starter/worker.test.js`
// Gercek ag yok: sahte fetch, sabit saat, sayilan uyku.
import assert from "node:assert/strict";
import { test } from "node:test";

import worker, {
  MAX_ATTEMPTS,
  PAGE_SIZE,
  REF,
  RETRY_DELAY_MS,
  WORKFLOW_FILE,
  classify,
  regularOpen,
  runsOfDay,
  sessionDay,
  start,
  windowOf,
} from "./worker.js";

const TOKEN = "pat-kanarya";
const BODY = "govde-gizli";
const WINTER = Date.UTC(2026, 0, 5, 13, 50, 3); // 5 Ocak 2026, 13:50:03Z; acilis 14:30Z
const UTC = (y, m, d, h, mi, s = 0) => Date.UTC(y, m - 1, d, h, mi, s);

function json(payload, status = 200, headers = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

function reply(status, headers = {}) {
  // 204 govdesizdir (Response kurucusu govdeyi reddeder); digerleri gizli govde tasir.
  return new Response(status === 204 ? null : BODY, { status, headers });
}

function listing(runs) {
  return json({ total_count: runs.length, workflow_runs: runs });
}

function run(id, created) {
  return { id, created_at: created, event: "schedule", head_branch: "main", status: "completed" };
}

/** Sahte fetch: cagrilari kaydeder, kuyruktaki yaniti verir (Error ise firlatir). */
function harness(queue, startAt = WINTER) {
  const calls = [];
  const sleeps = [];
  let clock = startAt;
  const fetchImpl = async (url, init) => {
    calls.push({ url: String(url), method: init.method, body: init.body, headers: init.headers });
    assert.ok(init.signal, "her istek zaman asimi sinyali tasir");
    const next = queue.shift();
    if (next === undefined) throw new Error("beklenmeyen istek: " + url);
    if (next instanceof Error) throw next;
    return next;
  };
  return {
    calls,
    sleeps,
    now: () => clock,
    sleep: async (ms) => {
      sleeps.push(ms);
      clock += ms;
    },
    fetchImpl,
    env: { STARTER_GITHUB_PAT: TOKEN },
    at: (ms) => {
      clock = ms;
    },
  };
}

async function go(h, extra = {}) {
  return start({
    env: h.env,
    fetchImpl: h.fetchImpl,
    now: h.now,
    sleep: h.sleep,
    scheduledTime: WINTER - 3000,
    cron: "50 13 * * 1-5",
    ...extra,
  });
}

const posts = (h) => h.calls.filter((c) => c.method === "POST");
const gets = (h) => h.calls.filter((c) => c.method === "GET");

// --------------------------------------------------------------------------
// Saat ve pencere
// --------------------------------------------------------------------------

test("acilis yaz/kis saatine gore hesaplanir (09:30 New York)", () => {
  assert.equal(regularOpen("2026-01-05"), UTC(2026, 1, 5, 14, 30)); // EST
  assert.equal(regularOpen("2026-03-06"), UTC(2026, 3, 6, 14, 30)); // DST oncesi cuma
  assert.equal(regularOpen("2026-03-09"), UTC(2026, 3, 9, 13, 30)); // DST sonrasi pazartesi
  assert.equal(regularOpen("2026-07-06"), UTC(2026, 7, 6, 13, 30)); // EDT
  assert.equal(regularOpen("2026-11-02"), UTC(2026, 11, 2, 14, 30)); // DST bitti
});

test("seans gunu New York takvim gunudur", () => {
  assert.equal(sessionDay(UTC(2026, 1, 5, 3, 0)), "2026-01-04"); // 22:00 EST onceki gun
  assert.equal(sessionDay(UTC(2026, 1, 5, 5, 0)), "2026-01-05");
  assert.equal(sessionDay(UTC(2026, 7, 6, 3, 30)), "2026-07-05"); // 23:30 EDT
});

test("iki cron satirindan her mevsimde tam biri pencereye duser", () => {
  for (const [y, m, d] of [[2026, 1, 5], [2026, 3, 9], [2026, 7, 6], [2026, 11, 2]]) {
    const inside = [[12, 50], [13, 50]].filter(([h, mi]) => windowOf(UTC(y, m, d, h, mi)).inside);
    assert.equal(inside.length, 1, `${y}-${m}-${d}: ${JSON.stringify(inside)}`);
  }
});

test("pencere [acilis - 60 dk, acilis - 1 dk] kapali araliktir", () => {
  const open = UTC(2026, 1, 5, 14, 30);
  assert.equal(windowOf(open - 60 * 60_000 - 1).inside, false);
  assert.equal(windowOf(open - 60 * 60_000).inside, true);
  assert.equal(windowOf(open - 60_000).inside, true);
  assert.equal(windowOf(open - 60_000 + 1).inside, false);
  assert.equal(windowOf(open).inside, false);
});

test("durum siniflari", () => {
  assert.equal(classify(204), "ok");
  for (const s of [429, 500, 502, 503, 599, "timeout", "network"]) assert.equal(classify(s), "retry");
  for (const s of [200, 400, 401, 403, 404, 422, 409, 600, null, undefined]) {
    assert.equal(classify(s), "fatal", String(s));
  }
});

test("kosu listesi: seans gunu suzulur, bicimsiz ya da cok sayfali liste hata", () => {
  const today = "2026-01-05";
  const runs = [run(1, "2026-01-05T13:50:03Z"), run(2, "2026-01-04T23:30:00Z"), run(3, "2026-01-05T03:00:00Z")];
  assert.deepEqual(runsOfDay({ total_count: 3, workflow_runs: runs }, today), [1]);
  assert.throws(() => runsOfDay({ total_count: PAGE_SIZE + 1, workflow_runs: [] }, today), /tek sayfayi/);
  assert.throws(() => runsOfDay({ workflow_runs: [] }, today), /tek sayfayi/);
  assert.throws(() => runsOfDay({ total_count: 1, workflow_runs: {} }, today), /bicimde/);
  assert.throws(() => runsOfDay(null, today), /bicimde/);
  assert.throws(() => runsOfDay({ total_count: 1, workflow_runs: [{ id: "1", created_at: "2026-01-05T13:50:03Z" }] }, today), /kosu kaydi/);
  assert.throws(() => runsOfDay({ total_count: 1, workflow_runs: [{ id: 1, created_at: "dun" }] }, today), /kosu kaydi/);
  assert.throws(() => runsOfDay({ total_count: 1, workflow_runs: [null] }, today), /kosu kaydi/);
});

// --------------------------------------------------------------------------
// Baslatma
// --------------------------------------------------------------------------

test("pencere disinda hic istek yapilmaz (mevsim disi satir, gec uyanis)", async () => {
  for (const at of [UTC(2026, 1, 5, 12, 50), UTC(2026, 1, 5, 14, 29, 1), UTC(2026, 1, 5, 17, 23)]) {
    const h = harness([], at);
    const line = await go(h);
    assert.equal(line.result, "pencere-disi");
    assert.equal(line.window, "disinda");
    assert.deepEqual(h.calls, []);
  }
});

test("secret yoksa hic istek yapilmaz", async () => {
  const h = harness([]);
  for (const env of [{}, { STARTER_GITHUB_PAT: "  " }, { STARTER_GITHUB_PAT: 5 }, undefined]) {
    const line = await go(h, { env });
    assert.equal(line.result, "secret-yok");
  }
  assert.deepEqual(h.calls, []);
});

test("temiz gun: once liste, sonra tek dispatch; sabit depo/workflow/ref, girdi yok", async () => {
  const h = harness([listing([run(7, "2026-01-02T13:50:03Z")]), reply(204)]);
  const line = await go(h);
  assert.equal(line.result, "dispatch");
  assert.equal(line.status, 204);
  assert.equal(line.attempts, 1);
  assert.equal(line.existing_run, null);
  assert.equal(line.window, "icinde");
  assert.equal(line.session_day, "2026-01-05");
  assert.equal(line.open, "2026-01-05T14:30:00.000Z");
  assert.equal(h.calls.length, 2);
  const [list, dispatch] = h.calls;
  assert.equal(
    list.url,
    `https://api.github.com/repos/dokuyucub/trading-lab/actions/workflows/${WORKFLOW_FILE}/runs?created=%3E%3D2026-01-04&per_page=${PAGE_SIZE}`,
  );
  assert.equal(
    dispatch.url,
    `https://api.github.com/repos/dokuyucub/trading-lab/actions/workflows/${WORKFLOW_FILE}/dispatches`,
  );
  assert.equal(dispatch.body, JSON.stringify({ ref: REF }));
  assert.equal(REF, "main");
  assert.ok(!dispatch.body.includes("inputs"));
  for (const call of h.calls) {
    assert.equal(call.headers.Authorization, `Bearer ${TOKEN}`);
    assert.equal(call.headers["User-Agent"], "trading-lab-shadow-starter");
    assert.equal(call.headers["X-GitHub-Api-Version"], "2022-11-28");
    assert.ok(call.url.startsWith("https://api.github.com/"));
  }
  assert.deepEqual(h.sleeps, []);
});

test("seans gununun kosusu varsa dispatch yok (cron geldi, ikinci dispatch, tekrar)", async () => {
  const h = harness([listing([run(40, "2026-01-05T13:23:49Z"), run(41, "2026-01-05T13:40:00Z")])]);
  const line = await go(h);
  assert.equal(line.result, "kosu-var");
  assert.equal(line.existing_run, 40);
  assert.equal(posts(h).length, 0);
});

test("onceki gunun gec kosusu bugunun kosusu sayilmaz", async () => {
  // 4 Ocak 23:30 EST = 5 Ocak 04:30Z: UTC tarihi bugun, New York gunu dun.
  const h = harness([listing([run(39, "2026-01-05T04:30:00Z")]), reply(204)]);
  const line = await go(h);
  assert.equal(line.result, "dispatch");
  assert.equal(posts(h).length, 1);
});

test("401/403/404/422 ve diger 4xx: tek deneme, tekrar yok", async () => {
  for (const status of [400, 401, 403, 404, 409, 422]) {
    const h = harness([listing([]), reply(status)]);
    const line = await go(h);
    assert.equal(line.result, "red", String(status));
    assert.equal(line.status, status);
    assert.equal(line.attempts, 1);
    assert.equal(posts(h).length, 1);
    assert.deepEqual(h.sleeps, []);
  }
});

test("429: Retry-After'a uyulur (30 sn'den kisa beklenmez), her denemeden once liste yinelenir", async () => {
  const h = harness([listing([]), reply(429, { "retry-after": "5" }), listing([]), reply(204)]);
  const line = await go(h);
  assert.equal(line.result, "dispatch");
  assert.equal(line.attempts, 2);
  assert.deepEqual(h.sleeps, [RETRY_DELAY_MS]);
  assert.equal(gets(h).length, 2);
  assert.equal(posts(h).length, 2);
});

test("429: uzun Retry-After beklenir ama pencerenin son dakikasini asacaksa durulur", async () => {
  const h = harness([listing([]), reply(429, { "retry-after": "120" }), listing([]), reply(204)]);
  const line = await go(h);
  assert.equal(line.result, "dispatch");
  assert.deepEqual(h.sleeps, [120_000]);

  const late = harness([listing([]), reply(429, { "retry-after": "600" })], UTC(2026, 1, 5, 14, 25));
  const stopped = await go(late);
  assert.equal(stopped.result, "son-dakika");
  assert.equal(stopped.attempts, 1);
  assert.deepEqual(late.sleeps, []);
  assert.equal(posts(late).length, 1);
});

test("5xx: en fazla uc deneme, 30 sn arayla", async () => {
  const h = harness([listing([]), reply(503), listing([]), reply(502), listing([]), reply(500)]);
  const line = await go(h);
  assert.equal(line.result, "vazgecildi");
  assert.equal(line.attempts, MAX_ATTEMPTS);
  assert.equal(line.status, 500);
  assert.deepEqual(h.sleeps, [RETRY_DELAY_MS, RETRY_DELAY_MS]);
  assert.equal(posts(h).length, 3);
  assert.equal(gets(h).length, 3);
});

test("zaman asimina ugrayan dispatch kosuyu olusturmus olabilir: tekrar once listeye bakar", async () => {
  const timeout = Object.assign(new Error("zaman asimi"), { name: "TimeoutError" });
  const h = harness([listing([]), timeout, listing([run(50, "2026-01-05T13:50:10Z")])]);
  const line = await go(h);
  assert.equal(line.result, "kosu-var");
  assert.equal(line.existing_run, 50);
  assert.equal(line.attempts, 2);
  assert.equal(posts(h).length, 1);
  assert.deepEqual(h.sleeps, [RETRY_DELAY_MS]);
});

test("ag hatasi da tekrar sinifidir; tekrar beklerken pencere kapanirsa dispatch yok", async () => {
  const h = harness([listing([]), new Error("baglanti koptu")], UTC(2026, 1, 5, 14, 28, 50));
  const line = await go(h);
  assert.equal(line.result, "son-dakika");
  assert.equal(line.status, "network");
  assert.deepEqual(h.sleeps, []);

  const h2 = harness([listing([]), new Error("baglanti koptu"), listing([])], UTC(2026, 1, 5, 14, 28, 20));
  h2.sleep = async (ms) => {
    h2.sleeps.push(ms);
    h2.at(UTC(2026, 1, 5, 14, 29, 30)); // bekleme sirasinda pencere gecti
  };
  const closed = await go(h2);
  assert.equal(closed.result, "pencere-kapandi");
  assert.equal(posts(h2).length, 1);
});

test("liste okunamazsa dispatch yok: cok sayfa, bicimsiz, 4xx; 5xx sinirli tekrar", async () => {
  const over = harness([json({ total_count: PAGE_SIZE + 1, workflow_runs: [] })]);
  assert.equal((await go(over)).result, "liste-okunamadi");
  assert.equal(posts(over).length, 0);

  const broken = harness([json({ workflow_runs: "yok" })]);
  assert.equal((await go(broken)).result, "liste-okunamadi");
  assert.equal(posts(broken).length, 0);

  const denied = harness([reply(403)]);
  const line = await go(denied);
  assert.equal(line.result, "liste-okunamadi");
  assert.equal(line.status, 403);
  assert.equal(denied.calls.length, 1);

  const flaky = harness([reply(503), reply(503), reply(503)]);
  const gaveUp = await go(flaky);
  assert.equal(gaveUp.result, "liste-okunamadi");
  assert.equal(gaveUp.attempts, MAX_ATTEMPTS);
  assert.deepEqual(flaky.sleeps, [RETRY_DELAY_MS, RETRY_DELAY_MS]);
  assert.equal(posts(flaky).length, 0);
});

test("log satirinda token ve yanit govdesi yoktur", async () => {
  for (const queue of [[listing([]), reply(403)], [reply(500), reply(500), reply(500)], [listing([]), reply(204)]]) {
    const h = harness(queue);
    const text = JSON.stringify(await go(h));
    assert.ok(!text.includes(TOKEN), text);
    assert.ok(!text.includes(BODY), text);
    assert.ok(!text.includes("Bearer"), text);
  }
});

test("scheduled isleyicisi tek satir JSON log yazar; fetch isleyicisi 404 doner", async () => {
  const originalFetch = globalThis.fetch;
  const originalLog = console.log;
  const logged = [];
  globalThis.fetch = async () => listing([run(60, "2026-01-05T13:50:03Z")]);
  console.log = (text) => logged.push(text);
  try {
    // Gercek saat pencere disinda olabilir: bu test yalnizca log satirini ve
    // ag disi yolu dogrular; dispatch'e varmadan "kosu-var" ya da "pencere-disi".
    await worker.scheduled({ scheduledTime: WINTER, cron: "50 13 * * 1-5" }, { STARTER_GITHUB_PAT: TOKEN });
  } finally {
    globalThis.fetch = originalFetch;
    console.log = originalLog;
  }
  assert.equal(logged.length, 1);
  const line = JSON.parse(logged[0]);
  assert.ok(["kosu-var", "pencere-disi"].includes(line.result), line.result);
  assert.equal(line.cron, "50 13 * * 1-5");
  assert.ok(!logged[0].includes(TOKEN));
  const response = await worker.fetch(new Request("https://example.invalid/"));
  assert.equal(response.status, 404);
});
