/**
 * Golge gozlem dis baslaticisi — Cloudflare Worker (Cron Trigger).
 *
 * Tasarim: docs/designs/scheduler-alternatives.md ("A'nin somut tasarimi";
 * Codex #17/6196548874 ve 6197450956). Tek is: hafta ici, acilistan ~40 dk
 * once, GitHub Actions'taki gozlem workflow'unu `main` dalinda BIR kez
 * baslatmak. Gozlemin kendisi, teklik kapisi ve kanit zinciri Actions'ta
 * kalir (docs/designs/shadow-observation.md §5-§6).
 *
 * Yapmadiklari: HTTP ile tetiklenmez (`fetch` her istege 404), girdi
 * gecirmez, planli gun listesini bilmez (kapi "plan disi" der), pencere
 * disinda dispatch etmez, `scheduledTime`'a degil gercek saate bakar,
 * token ya da yanit govdesini hicbir log satirina yazmaz.
 *
 * Bagimlilik yok; Node 22 `node --test` ile test edilir (worker.test.js).
 */

export const REPO = "dokuyucub/trading-lab";
export const WORKFLOW_FILE = "shadow-observation.yml";
export const REF = "main";
export const API = "https://api.github.com";
export const SECRET_NAME = "STARTER_GITHUB_PAT";
export const USER_AGENT = "trading-lab-shadow-starter";
/** Baslangic penceresi (tlab.shadow.schedule ile ayni): [acilis - 60, acilis - 1] dk. */
export const WINDOW_FIRST_MINUTES = 60;
export const WINDOW_LAST_MINUTES = 1;
/** 429/5xx/zaman asimi icin en fazla deneme; aralik; istek zaman asimi. */
export const MAX_ATTEMPTS = 3;
export const RETRY_DELAY_MS = 30_000;
export const TIMEOUT_MS = 20_000;
/** Kosu listesi tek sayfa; asarsa dispatch YOK (fail-closed). */
export const PAGE_SIZE = 100;
/** Gozlem workflow'unun kayit isi (tlab.shadow_job.RECORD_JOB ile ayni). */
export const RECORD_JOB = "record";

const EXCHANGE_TZ = "America/New_York";
const OPEN = { hour: 9, minute: 30 };
const MINUTE = 60_000;
const DAY = 86_400_000;

const PARTS = new Intl.DateTimeFormat("en-US", {
  timeZone: EXCHANGE_TZ,
  hourCycle: "h23",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

/** New York yerel takvim/saat parcalari ve o andaki UTC farki (ms). */
export function newYork(ms) {
  const parts = {};
  for (const { type, value } of PARTS.formatToParts(new Date(ms))) {
    if (type !== "literal") parts[type] = Number(value);
  }
  const asUtc = Date.UTC(
    parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second,
  );
  return { ...parts, offsetMs: asUtc - Math.floor(ms / 1000) * 1000 };
}

function isoDay(year, month, day) {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** Anin borsa yerel takvim gunu, "YYYY-MM-DD". */
export function sessionDay(ms) {
  const { year, month, day } = newYork(ms);
  return isoDay(year, month, day);
}

/** Gunun duzenli acilisi (09:30 New York), UTC ms; yaz/kis saati dilim kuralindan. */
export function regularOpen(day) {
  const [year, month, dayOfMonth] = day.split("-").map(Number);
  const naive = Date.UTC(year, month - 1, dayOfMonth, OPEN.hour, OPEN.minute);
  const candidate = naive - newYork(naive).offsetMs;
  return naive - newYork(candidate).offsetMs;
}

/** Baslangic penceresi: [acilis - 60 dk, acilis - 1 dk] (tasarim §5). */
export function windowOf(ms) {
  const day = sessionDay(ms);
  const open = regularOpen(day);
  const first = open - WINDOW_FIRST_MINUTES * MINUTE;
  const last = open - WINDOW_LAST_MINUTES * MINUTE;
  return { sessionDay: day, open, first, last, inside: ms >= first && ms <= last };
}

/** HTTP sonucunun sinifi: "ok" (204), "retry" (429, 5xx, zaman asimi, ag) ya da "fatal". */
export function classify(status) {
  if (status === 204) return "ok";
  if (status === "timeout" || status === "network") return "retry";
  if (status === 429 || (Number.isInteger(status) && status >= 500 && status <= 599)) {
    return "retry";
  }
  return "fatal";
}

/**
 * Kosu listesinden seans gunu `day` olan kosularin kimlikleri. Sekil bozuksa
 * ya da liste tek sayfayi asiyorsa hata: dispatch YOK (fail-closed).
 */
export function runsOfDay(payload, day) {
  if (!payload || typeof payload !== "object" || !Array.isArray(payload.workflow_runs)) {
    throw new Error("kosu listesi beklenen bicimde degil");
  }
  if (!Number.isInteger(payload.total_count) || payload.total_count > PAGE_SIZE) {
    throw new Error("kosu listesi tek sayfayi asti");
  }
  const ids = [];
  for (const run of payload.workflow_runs) {
    const created = run && typeof run === "object" ? Date.parse(run.created_at) : NaN;
    if (!run || !Number.isInteger(run.id) || Number.isNaN(created)) {
      throw new Error("kosu kaydi beklenen bicimde degil");
    }
    if (sessionDay(created) === day) ids.push(run.id);
  }
  return ids;
}

/**
 * Bir kosunun is listesi: kayit isi KANITLA atlandi mi (tasarim §5, kapinin
 * durum tablosu: tests/test_shadow_gate.py). Yalnizca kayit isi listede var
 * ve butun denemelerde `completed` + `skipped` ise kosu gunu tuketmemistir
 * (ornegin pencereden once kosan cron: kapi "erken", kayit atlandi). Kayit
 * isi yoksa, kuyrukta/suruyorsa ya da basarili/basarisiz/iptal bittiyse
 * kosu gunu tutar: dispatch YOK (fail-closed). Sekil bozuk ya da liste tek
 * sayfayi asiyorsa hata.
 */
export function recordSkipped(payload) {
  if (!payload || typeof payload !== "object" || !Array.isArray(payload.jobs)) {
    throw new Error("is listesi beklenen bicimde degil");
  }
  if (!Number.isInteger(payload.total_count) || payload.total_count > PAGE_SIZE) {
    throw new Error("is listesi tek sayfayi asti");
  }
  if (!payload.jobs.every((job) => job && typeof job === "object")) {
    throw new Error("is kaydi beklenen bicimde degil");
  }
  const record = payload.jobs.filter((job) => job.name === RECORD_JOB);
  return (
    record.length > 0 &&
    record.every((job) => job.status === "completed" && job.conclusion === "skipped")
  );
}

/**
 * `Retry-After` bekleme suresi (ms): yok ise 0; tam saniye ya da HTTP
 * tarihi; anlasilmayan deger NaN (cagiran fail-closed durur, sessizce
 * 30 sn'ye dusmez).
 */
export function retryAfterMs(response, nowMs) {
  const raw =
    response && response.headers && typeof response.headers.get === "function"
      ? response.headers.get("retry-after")
      : null;
  if (raw === null) return 0;
  const value = raw.trim();
  if (/^\d+$/.test(value)) return Number(value) * 1000;
  if (/^[A-Za-z]{3}, \d{2} [A-Za-z]{3} \d{4} \d{2}:\d{2}:\d{2} GMT$/.test(value)) {
    const at = Date.parse(value);
    if (!Number.isNaN(at)) return Math.max(0, at - nowMs);
  }
  return NaN;
}

/** Tekrardan once bekleme: en az RETRY_DELAY_MS, `Retry-After` daha uzunsa o. */
export function retryDelayMs(response, nowMs) {
  const asked = retryAfterMs(response, nowMs);
  return Number.isNaN(asked) ? NaN : Math.max(RETRY_DELAY_MS, asked);
}

function headersFor(token) {
  return {
    Authorization: `Bearer ${token}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": USER_AGENT,
  };
}

/** Istek; ag hatasi ya da zaman asimi sabit bir duruma donusur, firlatmaz. */
async function request(fetchImpl, url, init) {
  try {
    return await fetchImpl(url, { ...init, signal: AbortSignal.timeout(TIMEOUT_MS) });
  } catch (error) {
    const status = error && error.name === "TimeoutError" ? "timeout" : "network";
    return { status, headers: new Headers() };
  }
}

function defaultSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Teklik on kontrolu: o seans gununun kosulari ve her birinin kayit isi.
 * Sonuc: { kind: "ok" } | { kind: "block", id } | { kind: "retry", response }
 * | { kind: "fail" }. `line.status` son istegin durumunu, `line.skipped_runs`
 * kayit isi kanitla atlanmis kosu sayisini tasir.
 */
async function precheck(fetchImpl, listUrl, runsBase, headers, sessionDayValue, line) {
  const listed = await request(fetchImpl, listUrl, { method: "GET", headers });
  line.status = listed.status;
  if (listed.status !== 200) {
    return classify(listed.status) === "retry" ? { kind: "retry", response: listed } : { kind: "fail" };
  }
  let ids;
  try {
    ids = runsOfDay(await listed.json(), sessionDayValue);
  } catch {
    return { kind: "fail" };
  }
  let skipped = 0;
  for (const id of ids) {
    const jobs = await request(fetchImpl, `${runsBase}/${id}/jobs?filter=all&per_page=${PAGE_SIZE}`, {
      method: "GET",
      headers,
    });
    line.status = jobs.status;
    if (jobs.status !== 200) {
      return classify(jobs.status) === "retry" ? { kind: "retry", response: jobs } : { kind: "fail" };
    }
    let free;
    try {
      free = recordSkipped(await jobs.json());
    } catch {
      return { kind: "fail" };
    }
    if (!free) {
      line.skipped_runs = skipped;
      return { kind: "block", id };
    }
    skipped += 1;
  }
  line.skipped_runs = skipped;
  return { kind: "ok" };
}

/**
 * Baslaticinin tek calismasi. Log satirini DONDURUR; satirda token, yanit
 * govdesi, fiyat ya da hesap bilgisi yoktur. Sonuclar:
 *   pencere-disi         gercek saat pencere disinda; hic istek yok
 *   secret-yok           ortamda PAT yok; hic istek yok
 *   liste-okunamadi      kosu ya da is listesi alinamadi/bicimsiz/tek sayfayi
 *                        asti; dispatch yok
 *   kosu-var             seans gununun kayit isi atlanmamis (ya da belirsiz)
 *                        bir kosusu var; dispatch yok
 *   dispatch             204 alindi (gozlemin basladigi anlamina GELMEZ)
 *   red                  401/403/404/422 ya da baska 4xx; tekrar yok
 *   pencere-kapandi      tekrar beklerken pencere gecti
 *   son-dakika           bekleme pencerenin son dakikasini asacakti
 *   retry-after-belirsiz `Retry-After` anlasilamadi; tekrar yok
 *   vazgecildi           en fazla deneme sayisi doldu
 */
export async function start({
  env,
  fetchImpl = fetch,
  now = Date.now,
  sleep = defaultSleep,
  scheduledTime = null,
  cron = null,
}) {
  const started = now();
  const window = windowOf(started);
  const line = {
    scheduled: scheduledTime === null ? null : new Date(scheduledTime).toISOString(),
    cron,
    started: new Date(started).toISOString(),
    session_day: window.sessionDay,
    open: new Date(window.open).toISOString(),
    window: window.inside ? "icinde" : "disinda",
    existing_run: null,
    skipped_runs: 0,
    attempts: 0,
    status: null,
    result: null,
  };
  if (!window.inside) return { ...line, result: "pencere-disi" };
  const token = env && typeof env[SECRET_NAME] === "string" ? env[SECRET_NAME].trim() : "";
  if (!token) return { ...line, result: "secret-yok" };

  const base = `${API}/repos/${REPO}/actions/workflows/${WORKFLOW_FILE}`;
  const runsBase = `${API}/repos/${REPO}/actions/runs`;
  const [year, month, day] = window.sessionDay.split("-").map(Number);
  const since = new Date(Date.UTC(year, month - 1, day) - DAY).toISOString().slice(0, 10);
  const listUrl = `${base}/runs?created=${encodeURIComponent(`>=${since}`)}&per_page=${PAGE_SIZE}`;
  const headers = headersFor(token);

  // Tekrar bekleyisi, GET ve POST icin ayni: Retry-After, alt sinir ve
  // pencerenin son dakikasi. null = bekle ve devam; aksi halde sonuc.
  const waitOrStop = async (response) => {
    const delay = retryDelayMs(response, now());
    if (Number.isNaN(delay)) return "retry-after-belirsiz";
    if (now() + delay > window.last) return "son-dakika";
    await sleep(delay);
    return null;
  };

  for (;;) {
    line.attempts += 1;
    // 1. Teklik on kontrolu, HER denemede: zaman asimina ugrayan bir istek
    //    kosuyu olusturmus olabilir; cron da ayni gun gelmis olabilir.
    const check = await precheck(fetchImpl, listUrl, runsBase, headers, window.sessionDay, line);
    if (check.kind === "fail") return { ...line, result: "liste-okunamadi" };
    if (check.kind === "block") return { ...line, existing_run: check.id, result: "kosu-var" };
    if (check.kind === "retry") {
      if (line.attempts >= MAX_ATTEMPTS) return { ...line, result: "liste-okunamadi" };
      const stop = await waitOrStop(check.response);
      if (stop) return { ...line, result: stop };
      continue;
    }
    // 2. Pencere yeniden, gercek saatle (gec uyanis, uzun bekleme).
    if (now() > window.last) return { ...line, result: "pencere-kapandi" };
    // 3. Dispatch: sabit depo, workflow ve ref; girdi yok.
    const response = await request(fetchImpl, `${base}/dispatches`, {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({ ref: REF }),
    });
    line.status = response.status;
    const kind = classify(response.status);
    if (kind === "ok") return { ...line, result: "dispatch" };
    if (kind === "fatal") return { ...line, result: "red" };
    if (line.attempts >= MAX_ATTEMPTS) return { ...line, result: "vazgecildi" };
    const stop = await waitOrStop(response);
    if (stop) return { ...line, result: stop };
  }
}

export default {
  async scheduled(event, env) {
    const line = await start({ env, scheduledTime: event.scheduledTime, cron: event.cron });
    console.log(JSON.stringify(line));
  },
  fetch() {
    return new Response(null, { status: 404 });
  },
};
