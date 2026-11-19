/* Past paper question database: static single-page catalogue.
 * Data: data/index.json, data/<subject>.json (+ optional data/<subject>.text.json), img/<exam_id>/<file>.
 * Transcriptions are rendered by richtext.js; maths by KaTeX (vendor/katex/, loaded on first use).
 * Routes (hash): #/questions?…  #/q/<id>?…  #/papers?…  #/paper/<exam_id>?ms=…  #/topics?…  #/practice?…  #/help
 */
(function () {
  "use strict";

  var BUILD = "__BUILD_ID__";
  var APP = "Past paper question database";
  var SUBJ_SHORT = { math: "Math", physics: "Physics", economics: "Economics" };
  var PAPER_ORDER = ["1", "1A", "1B", "2", "3"];
  var TZ_ORDER = ["TZ1", "TZ2", "TZ3"];
  var QTYPE_NAMES = { mcq: "Multiple choice", short: "Short response", long: "Extended response",
    essay: "Essay", data: "Data-based", none: "Unspecified" };
  var QTYPE_ORDER = ["mcq", "short", "long", "essay", "data", "none"];
  var ANS_NAMES = { ok: "Available", suspect: "Suspect", missing: "Missing" };
  var ANS_FACET = { ok: "Has markscheme", suspect: "Has markscheme, match uncertain", missing: "No markscheme" };
  var ANS_ORDER = ["ok", "suspect", "missing"];
  // Per-question flags (db/SCHEMA.md). label: shown on the question page; tag: short form in the results table.
  var FLAG_INFO = {
    "key-disputed": { label: "Answer key disputed", tag: "Key disputed", desc: "The official multiple-choice key is believed to be wrong; the reason is given beside the answer." },
    "crop-bad": { label: "Image crop faulty", tag: "Crop", desc: "The page image of this question is cut off or contains material from a neighbouring question." },
    "crop-uncertain": { label: "Image crop uncertain", tag: "Crop", desc: "The boundaries of the page image could not be determined with certainty." },
    "text-ocr": { label: "Scanned paper (text by OCR)", desc: "The source paper is a scan; its text layer was produced by optical character recognition." },
    "topic-uncertain": { label: "Topic uncertain", tag: "Topic uncertain", desc: "No topic code fits exactly; the closest codes were used." },
    "content-removed": { label: "Content removed for copyright", tag: "Part removed", desc: "Part of this question (for example a text extract or a figure) is missing from the published paper for copyright reasons." },
    "parts-removed": { label: "Question removed for copyright", tag: "Removed", desc: "The question itself is missing from the published paper for copyright reasons; only the markscheme remains." },
    "source-incomplete": { label: "Source paper incomplete", tag: "Incomplete", desc: "The available copy of the paper is missing part of this question." },
    "diagram-heavy": { label: "Diagram-heavy", desc: "The question relies on a diagram; see the page image." },
    "marks-from-ms": { label: "Marks taken from markscheme", desc: "The paper does not print the total; it was taken from the markscheme." },
    "downscaled": { label: "Image downscaled", desc: "The page image was reduced in size to fit the hosting limits." },
    "mcq-multiple-answers": { label: "Several answers accepted", tag: "Several keys", desc: "The markscheme accepts more than one option." }
  };
  function flagLabel(f) { return FLAG_INFO[f] ? FLAG_INFO[f].label : f; }
  // Values of the "Flags" filter: reader-facing groups of flags (plus derived properties).
  var ISSUES = [
    ["key-disputed", "Answer key disputed", ["key-disputed"]],
    ["crop", "Image crop problem", ["crop-bad", "crop-uncertain"]],
    ["text-ocr", "Scanned paper (OCR text)", ["text-ocr"]],
    ["topic-uncertain", "Topic uncertain", ["topic-uncertain"]],
    ["content-removed", "Content partly removed", ["content-removed"]],
    ["source-incomplete", "Source paper incomplete", ["source-incomplete"]],
    ["diagram-heavy", "Diagram-heavy", ["diagram-heavy"]],
    ["multiple-answers", "Several answers accepted", ["mcq-multiple-answers"]],
    ["repeat", "Also in another paper", null],
    ["auto-text", "No checked transcription", null],
    ["note", "Has a reviewer note", null]
  ];
  var ISSUE_ORDER = ISSUES.map(function (x) { return x[0]; }).concat("none");
  var ISSUE_NAMES = { none: "No flags" }, FLAG_ISSUE = {};
  ISSUES.forEach(function (x) { ISSUE_NAMES[x[0]] = x[1]; (x[2] || []).forEach(function (f) { FLAG_ISSUE[f] = x[0]; }); });
  // "Hide repeated questions": default per view (lists are catalogues; counts and practice sets are not)
  var DUP_DEFAULT = { questions: false, q: false, papers: false, paper: false, practice: true, topics: true };
  var STATUS_NAMES = { done: "Extracted", partial: "Partly extracted", failed: "Extraction failed",
    unprocessed: "Not yet extracted" };
  var STATUS_ORDER = ["done", "partial", "failed", "unprocessed"];
  var LEVEL_NAMES = { HL: "HL", SL: "SL", HLSL: "HL and SL", none: "Unspecified" };
  var PER_PAGE = [25, 50, 100, 200, 500];
  var P_ORDER = ["subject", "syllabus", "exam", "year", "session", "tz", "paper", "option", "level", "status",
    "section", "qtype", "marks", "topic", "sub", "tmode", "ans", "flag", "dup", "removed", "q", "in", "group", "sort",
    "per", "page", "n", "seed", "ms", "rows", "cols", "tcount", "at"];
  var FILTER_KEYS = ["subject", "syllabus", "exam", "year", "session", "tz", "paper", "option", "section", "qtype",
    "marks", "topic", "sub", "tmode", "ans", "flag", "dup", "removed", "q", "in"];

  // ---------------------------------------------------------------- utilities
  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
  var ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" };
  function esc(v) { return v == null ? "" : String(v).replace(/[&<>"']/g, function (c) { return ESC[c]; }); }
  function fmt(n) { return Number(n).toLocaleString("en-US"); }
  function plural(n, w, pl) { return fmt(n) + " " + (n === 1 ? w : (pl || w + "s")); }
  function slug(s) { return String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, ""); }
  function idSafe(s) { return String(s).replace(/[^A-Za-z0-9_-]/g, function (c) { return "_" + c.charCodeAt(0); }); }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  var collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });
  function idx(arr, v) { var i = arr.indexOf(v); return i < 0 ? arr.length : i; }
  function debounce(fn, ms) {
    var t = null;
    return function () { var a = arguments, s = this; clearTimeout(t); t = setTimeout(function () { fn.apply(s, a); }, ms); };
  }
  function imgUrl(ex, name) { return "img/" + encodeURIComponent(ex.id) + "/" + encodeURIComponent(name); }

  // ---------------------------------------------------------------- preferences (display only)
  var prefs = { theme: "auto", invert: false, qview: "both" };
  var QVIEWS = ["both", "image", "text"];
  try {
    var sp = JSON.parse(localStorage.getItem("qdb-prefs") || "{}");
    if (sp && typeof sp === "object") { prefs.theme = sp.theme || "auto"; prefs.invert = !!sp.invert; if (QVIEWS.indexOf(sp.qview) >= 0) prefs.qview = sp.qview; }
  } catch (e) { /* storage unavailable */ }
  function savePrefs() { try { localStorage.setItem("qdb-prefs", JSON.stringify(prefs)); } catch (e) { /* ignore */ } }
  function applyPrefs() {
    document.documentElement.setAttribute("data-theme", prefs.theme);
    document.documentElement.setAttribute("data-invert", prefs.invert ? "1" : "0");
  }

  // ---------------------------------------------------------------- maths rendering (KaTeX, loaded on first use)
  // Elements produced by richHtml() show the plain text at once (kept invisible for a moment by the
  // .tex-pending class) and are re-rendered with KaTeX once it has loaded. If KaTeX cannot be loaded, or a
  // formula does not parse, the LaTeX source stays visible as plain text.
  var KX = { state: "none", promise: null, lib: null };
  var richReg = new Map(), richSeq = 0;
  function loadKatex() {
    if (KX.promise) return KX.promise;
    KX.promise = new Promise(function (resolve) {
      var done = function (lib) { KX.lib = lib; KX.state = lib ? "ready" : "failed"; resolve(lib); };
      var css = document.createElement("link");
      css.rel = "stylesheet"; css.href = "vendor/katex/katex.min.css?v=" + BUILD;
      document.head.appendChild(css);
      var sc = document.createElement("script");
      sc.src = "vendor/katex/katex.min.js?v=" + BUILD; sc.async = true;
      sc.onload = function () { done(window.katex && typeof window.katex.renderToString === "function" ? window.katex : null); };
      sc.onerror = function () { done(null); };
      document.head.appendChild(sc);
    });
    return KX.promise;
  }
  // block: keep line structure (transcriptions); otherwise inline (notes). Returns an HTML string.
  function richHtml(text, block, tag) {
    tag = tag || "div";
    var cls = block ? "rich" : "rich-inline";
    var Q = window.QText;
    if (!Q) return "<" + tag + " class=\"" + cls + " plain\">" + esc(text) + "</" + tag + ">";
    var fn = block ? Q.html : Q.inlineHtml;
    if (!Q.hasMath(text) || KX.state === "ready" || KX.state === "failed") {
      return "<" + tag + " class=\"" + cls + "\">" + fn(text, KX.lib) + "</" + tag + ">";
    }
    var id = String(++richSeq);
    richReg.set(id, { text: text, block: block });
    return "<" + tag + " class=\"" + cls + " tex-pending\" data-tex=\"" + id + "\">" + fn(text, null) + "</" + tag + ">";
  }
  // Call after inserting richHtml() output into the page.
  function upgradeTex(root) {
    var els = $$("[data-tex]", root || document);
    if (!els.length) return;
    loadKatex().then(function (lib) {
      els.forEach(function (el) {
        var item = richReg.get(el.getAttribute("data-tex"));
        richReg["delete"](el.getAttribute("data-tex"));
        el.removeAttribute("data-tex");
        el.classList.remove("tex-pending");
        if (!item || !el.isConnected || !lib) return;
        el.innerHTML = (item.block ? window.QText.html : window.QText.inlineHtml)(item.text, lib);
      });
    });
  }

  // ---------------------------------------------------------------- URL parameters
  function encodeVal(v) { return encodeURIComponent(v).replace(/%2C/gi, ",").replace(/%3A/gi, ":"); }
  function hashOf(view, arg, params) {
    var h = "#/" + view + (arg ? "/" + encodeURIComponent(arg) : "");
    var keys = Object.keys(params || {}).filter(function (k) { return params[k] != null && params[k] !== ""; });
    keys.sort(function (a, b) { return idx(P_ORDER, a) - idx(P_ORDER, b) || (a < b ? -1 : 1); });
    if (keys.length) h += "?" + keys.map(function (k) { return k + "=" + encodeVal(params[k]); }).join("&");
    return h;
  }
  function parseHash() { return parseHashStr(location.hash); }
  function parseHashStr(hash) {
    var h = String(hash || "").replace(/^#\/?/, "");
    var qi = h.indexOf("?");
    var path = qi < 0 ? h : h.slice(0, qi);
    var qs = qi < 0 ? "" : h.slice(qi + 1);
    var parts = path.split("/");
    var params = {};
    new URLSearchParams(qs).forEach(function (v, k) { if (v !== "") params[k] = v; });
    var arg = "";
    try { arg = decodeURIComponent(parts.slice(1).join("/")); } catch (e) { arg = parts.slice(1).join("/"); }
    return { view: parts[0] || "", arg: arg, params: params };
  }
  function list(params, k) { return params[k] ? String(params[k]).split(",").filter(Boolean) : []; }
  function pick(params, keys) {
    var o = {};
    keys.forEach(function (k) { if (params[k] != null && params[k] !== "") o[k] = params[k]; });
    return o;
  }
  function assign(a, b) { var o = {}, k; for (k in a) o[k] = a[k]; for (k in b) { if (b[k] == null || b[k] === "") delete o[k]; else o[k] = b[k]; } return o; }
  function parseRange(s) {
    if (!s) return null;
    var m = /^\s*(\d*)\s*(?:-\s*(\d*))?\s*$/.exec(String(s));
    if (!m) return null;
    var lo = m[1] === "" ? -Infinity : +m[1];
    var hi = m[2] === undefined ? lo : (m[2] === "" ? Infinity : +m[2]);
    if (lo === -Infinity && hi === Infinity) return null;
    if (lo > hi) { var t = lo; lo = hi; hi = t; }
    return [lo, hi];
  }
  function rangeStr(lo, hi) {
    if (lo === "" && hi === "") return "";
    if (lo !== "" && hi !== "" && lo === hi) return String(lo);
    return lo + "-" + hi;
  }

  // ---------------------------------------------------------------- data
  var DB = { index: null, list: [], byId: {}, rows: [], exams: [], rowById: new Map(), examById: new Map(),
    sylNames: {}, sylShort: {}, optNames: {}, years: [] };

  function fetchJSON(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error(url.replace(/\?.*$/, "") + ": HTTP " + r.status);
      return r.json();
    });
  }

  function load() {
    return fetchJSON("data/index.json?v=" + BUILD).then(function (index) {
      DB.index = index;
      var subs = index.subjects || [];
      return Promise.all(subs.map(function (s) { return fetchJSON("data/" + s.file + "?v=" + BUILD); }))
        .then(function (files) { files.forEach(function (j, i) { ingest(subs[i], j, i); }); finalize(); });
    });
  }

  function ingest(meta, j, order) {
    var S = { id: j.subject || meta.id, name: j.name || meta.name || meta.id, ord: order,
      syllabuses: j.syllabuses || [], tax: [], codes: new Map(), exams: [], rows: [], groups: new Map(),
      textFile: meta.text_file || null, textState: meta.text_file ? "none" : "ready", textPromise: null };
    S.short = SUBJ_SHORT[S.id] || S.name;
    S.syllabuses.forEach(function (sy) { DB.sylNames[sy.id] = sy.name; DB.sylShort[sy.id] = sy.short || sy.name; });
    var ord = 0;
    (j.taxonomy || []).forEach(function (t) {
      var T = { code: t.c, name: t.n, ord: ord++, parent: null, subs: [] };
      S.codes.set(T.code, T); S.tax.push(T);
      (t.s || []).forEach(function (st) {
        var U = { code: st.c, name: st.n, ord: ord++, parent: T, subs: null };
        T.subs.push(U); S.codes.set(U.code, U);
      });
    });
    (j.exams || []).forEach(function (e) {
      var ex = { id: e.id, S: S, sy: e.sy || null, year: e.y, session: e.s, tz: e.tz || null, paper: String(e.p),
        option: e.o || null, level: e.l || null, status: e.st || "unprocessed", pages: e.pg || null,
        hasMs: !!e.ms, src: e.src || null, mss: e.mss || null, code: e.cd || null, pnum: e.pn || null,
        notes: e.nt || null, nq: e.nq || 0, marks: e.mk || 0, qs: [] };
      ex.optSlug = ex.option ? slug(ex.option) : null;
      if (ex.option) DB.optNames[ex.optSlug] = ex.option;
      ex.sessIdx = ex.session === "November" ? 1 : 0;
      ex.tzIdx = ex.tz ? idx(TZ_ORDER, ex.tz) + 1 : 0;
      ex.paperIdx = idx(PAPER_ORDER, ex.paper);
      S.exams.push(ex);
    });
    (j.questions || []).forEach(function (q) {
      var ex = S.exams[q.e];
      if (!ex) return;
      var r = { id: q.id, S: S, ex: ex, num: String(q.n), sec: q.sc || null, marks: q.m == null ? null : q.m,
        type: q.t || null, img: q.im || null, iz: q.iz || null, msImg: q.ms || null, mz: q.mz || null,
        mcq: q.a || null, tp: q.tp || [], su: q.su || [], ans: q.as || "missing", flags: q.f || [],
        text: q.x == null ? null : q.x, mstext: q.y == null ? null : q.y, pos: ex.qs.length,
        note: q.rn || null, clean: !!q.xc, dg: q.dg || null, dr: q.dr || 0, gk: q.dg ? S.id + ":" + q.dg : null, dups: [] };
      var m = /^(\d+)(.*)$/.exec(r.num);
      r.numKey = m ? +m[1] * 1000 + (m[2] ? Math.min(999, m[2].charCodeAt(0)) : 0) : 999999;
      r.typeIdx = idx(QTYPE_ORDER, r.type || "none");
      r.tcodes = r.tp.length ? r.tp.concat(r.su) : ["none"];
      r.tset = new Set(r.tcodes);
      // primary topic = first listed; primary subtopic = first listed subtopic of the primary topic
      r.psub = null;
      for (var si = 0; si < r.su.length && r.tp.length; si++) {
        var sc = S.codes.get(r.su[si]);
        if (sc && sc.parent && sc.parent.code === r.tp[0]) { r.psub = r.su[si]; break; }
      }
      r.pcodes = r.tp.length ? (r.psub ? [r.tp[0], r.psub] : [r.tp[0]]) : ["none"];
      r.pset = new Set(r.pcodes);
      var pt = r.tp.length ? S.codes.get(r.tp[0]) : null;
      r.topicKey = pt ? pt.ord : null;
      r.removed = r.flags.indexOf("parts-removed") >= 0;
      r.partRemoved = !r.removed && r.flags.indexOf("content-removed") >= 0;
      r.disputed = r.flags.indexOf("key-disputed") >= 0;
      ex.qs.push(r);
      S.rows.push(r);
      if (r.gk) { var G = S.groups.get(r.gk); if (!G) S.groups.set(r.gk, G = []); G.push(r); }
    });
    S.groups.forEach(function (G) {
      G.sort(function (a, b) { return a.dr - b.dr; });
      G.forEach(function (r) { r.dups = G.filter(function (x) { return x !== r; }); });
    });
    S.rows.forEach(function (r) {
      var iss = [];
      r.flags.forEach(function (f) { var k = FLAG_ISSUE[f]; if (k && iss.indexOf(k) < 0) iss.push(k); });
      if (r.dups.length) iss.push("repeat");
      if (!r.clean) iss.push("auto-text");
      if (r.note) iss.push("note");
      r.iss = iss.length ? iss : NONE;
      r.tags = [];
      if (r.dups.length) r.tags.push(["Repeat", "Also in " + r.dups.map(function (d) { return d.id; }).join(", ")]);
      r.flags.forEach(function (f) { var I = FLAG_INFO[f]; if (I && I.tag) r.tags.push([I.tag, I.label + ": " + I.desc]); });
    });
    DB.list.push(S);
    DB.byId[S.id] = S;
  }

  function finalize() {
    var exams = [];
    DB.list.forEach(function (S) { exams = exams.concat(S.exams); });
    var optList = Object.keys(DB.optNames).sort(collator.compare);
    exams.forEach(function (ex) { ex.optRank = ex.optSlug ? optList.indexOf(ex.optSlug) : null; });
    exams.sort(function (a, b) {
      return a.S.ord - b.S.ord || b.year - a.year || b.sessIdx - a.sessIdx || a.paperIdx - b.paperIdx ||
        (a.optRank == null ? -1 : a.optRank) - (b.optRank == null ? -1 : b.optRank) || a.tzIdx - b.tzIdx ||
        collator.compare(a.id, b.id);
    });
    exams.forEach(function (ex, i) { ex.ord = i; DB.examById.set(ex.id, ex); });
    DB.exams = exams;
    var rows = [];
    exams.forEach(function (ex) { rows = rows.concat(ex.qs); });
    rows.forEach(function (r, i) { r.ord = i; DB.rowById.set(r.id, r); });
    DB.rows = rows;
    DB.list.forEach(function (S) { S.rows.sort(function (a, b) { return a.ord - b.ord; }); S.exams.sort(function (a, b) { return a.ord - b.ord; }); });
    var ids = rows.slice().sort(function (a, b) { return collator.compare(a.id, b.id); });
    ids.forEach(function (r, i) { r.idRank = i; });
    var eids = exams.slice().sort(function (a, b) { return collator.compare(a.id, b.id); });
    eids.forEach(function (ex, i) { ex.idRank = i; });
    var ys = {};
    exams.forEach(function (ex) { ys[ex.year] = 1; });
    DB.years = Object.keys(ys).map(Number).sort(function (a, b) { return a - b; });
  }

  function subjectsFor(subj) { return subj ? [DB.byId[subj]] : DB.list; }
  function validSubject(s) { return s && DB.byId[s] ? s : ""; }
  function textReady(subjs) { return subjs.every(function (S) { return S.textState === "ready"; }); }
  function ensureText(subjs) {
    return Promise.all(subjs.map(function (S) {
      if (S.textState === "ready") return null;
      if (!S.textPromise) {
        S.textState = "loading";
        S.textPromise = fetchJSON("data/" + S.textFile + "?v=" + BUILD).then(function (t) {
          S.rows.forEach(function (r) {
            var v = t[r.id];
            if (v) { r.text = v[0] == null ? null : v[0]; r.mstext = v[1] == null ? null : v[1]; }
            r.hq = r.hm = undefined;
          });
          S.textState = "ready";
          qcache.key = null;
        }, function (err) { S.textState = "error"; S.textPromise = null; throw err; });
      }
      return S.textPromise;
    }));
  }

  function examTitle(ex, withSubject) {
    var s = (withSubject ? ex.S.name + ", " : "") + ex.session + " " + ex.year + ", Paper " + ex.paper;
    if (ex.option) s += " (" + ex.option + ")";
    if (ex.tz) s += ", " + ex.tz;
    return s;
  }
  function examShort(ex) {
    return ex.S.short + " " + ex.year + " " + (ex.session === "November" ? "Nov" : "May") + " P" + ex.paper +
      (ex.option ? " " + ex.option : "") + (ex.tz ? " " + ex.tz : "");
  }
  function codeName(S, code) { var c = S.codes.get(code); return c ? c.name : code; }

  // ---------------------------------------------------------------- search
  function parseSearch(q) {
    var terms = [];
    if (!q) return terms;
    var re = /(-?)"([^"]*)"|(-?)(\S+)/g, m;
    while ((m = re.exec(String(q)))) {
      var neg = !!(m[1] || m[3]);
      var t = (m[2] != null ? m[2] : m[4]).toLowerCase().replace(/\s+/g, " ").trim();
      if (t && t !== "-") terms.push({ t: t, neg: neg });
    }
    return terms;
  }
  function norm(s) { return s ? s.toLowerCase().replace(/\s+/g, " ") : ""; }
  // transcriptions keep LaTeX; searching and snippets ignore the $ delimiters ("\theta < 0.61" matches "theta")
  function plainQ(r) { return r.text && r.clean ? r.text.replace(/\$/g, "") : r.text; }
  function hayQ(r) { if (r.hq === undefined) r.hq = r.id.toLowerCase() + " " + norm(plainQ(r)); return r.hq; }
  function hayM(r) { if (r.hm === undefined) r.hm = norm(r.mstext); return r.hm; }
  function matchSearch(r, terms, where) {
    for (var i = 0; i < terms.length; i++) {
      var t = terms[i].t, hit;
      if (where === "q") hit = hayQ(r).indexOf(t) >= 0;
      else if (where === "ms") hit = hayM(r).indexOf(t) >= 0;
      else hit = hayQ(r).indexOf(t) >= 0 || hayM(r).indexOf(t) >= 0;
      if (hit === terms[i].neg) return false;
    }
    return true;
  }
  function snippet(r, terms, where) {
    var pos = terms.filter(function (t) { return !t.neg; });
    if (!pos.length) return "";
    var srcs = where === "ms" ? [r.mstext] : where === "q" ? [plainQ(r)] : [plainQ(r), r.mstext];
    for (var s = 0; s < srcs.length; s++) {
      var txt = srcs[s] ? srcs[s].replace(/\s+/g, " ") : "";
      var low = txt.toLowerCase(), at = -1;
      for (var i = 0; i < pos.length && at < 0; i++) at = low.indexOf(pos[i].t);
      if (at < 0) continue;
      var a = Math.max(0, at - 70), b = Math.min(txt.length, at + 150);
      var piece = txt.slice(a, b);
      var html = highlight(piece, pos);
      return (s === 1 || where === "ms" ? "<b>Markscheme:</b> " : "") + (a > 0 ? "&hellip;" : "") + html +
        (b < txt.length ? "&hellip;" : "");
    }
    return "";
  }
  function highlight(text, pos) {
    var low = text.toLowerCase(), marks = [];
    pos.forEach(function (p) {
      var i = 0;
      while ((i = low.indexOf(p.t, i)) >= 0) { marks.push([i, i + p.t.length]); i += p.t.length; }
    });
    marks.sort(function (x, y) { return x[0] - y[0]; });
    var out = "", last = 0;
    marks.forEach(function (m) {
      if (m[0] < last) return;
      out += esc(text.slice(last, m[0])) + "<mark>" + esc(text.slice(m[0], m[1])) + "</mark>";
      last = m[1];
    });
    return out + esc(text.slice(last));
  }

  // ---------------------------------------------------------------- facets
  function single(get) { return { get: get, test: function (r, s) { return s.set.has(get(r)); } }; }
  function multi(get) {
    return { get: get, test: function (r, s) { var v = get(r); for (var i = 0; i < v.length; i++) if (s.set.has(v[i])) return true; return false; } };
  }
  var NONE = ["none"];
  function facet(p, label, impl, extra) { var f = { p: p, label: label, get: impl.get, test: impl.test }; for (var k in extra) f[k] = extra[k]; return f; }

  var QFACETS = [
    facet("syllabus", "Syllabus", single(function (r) { return r.ex.sy || "none"; }), { lab: sylLabel }),
    facet("session", "Session", single(function (r) { return r.ex.session; }), { order: ["May", "November"] }),
    facet("tz", "Time zone", single(function (r) { return r.ex.tz || "none"; }), { order: TZ_ORDER.concat("none"), lab: tzLabel }),
    facet("paper", "Paper", single(function (r) { return r.ex.paper; }), { order: PAPER_ORDER, lab: function (v) { return "Paper " + v; } }),
    facet("option", "Paper 3 option", single(function (r) { return r.ex.optSlug || "none"; }), { lab: optLabel, last: "none" }),
    facet("section", "Section", single(function (r) { return r.sec || "none"; }), { lab: function (v) { return v === "none" ? "No section" : "Section " + v; }, last: "none" }),
    facet("qtype", "Question type", single(function (r) { return r.type || "none"; }), { order: QTYPE_ORDER, lab: function (v) { return QTYPE_NAMES[v] || v; } }),
    facet("ans", "Markscheme", single(function (r) { return r.ans; }), { order: ANS_ORDER, lab: function (v) { return ANS_FACET[v] || v; } }),
    facet("flag", "Flags", multi(function (r) { return r.iss; }), { order: ISSUE_ORDER, lab: function (v) { return ISSUE_NAMES[v] || flagLabel(v); },
      // older links used raw flag names
      alias: function (v) { return FLAG_ISSUE[v] || v; } }),
    { p: "topic", label: "Topics", topic: true,
      get: function (r) { return r.tcodes; },
      test: function (r, s) {
        var i, v = s.vals;
        if (s.mode === "all") { for (i = 0; i < v.length; i++) if (!r.tset.has(v[i])) return false; return true; }
        for (i = 0; i < v.length; i++) if (r.tset.has(v[i])) return true;
        return false;
      } }
  ];
  // topic facet when matching the primary topic / subtopic only (tmode=primary)
  var PRIMARY_TOPIC_FACET = { p: "topic", label: "Topics", topic: true,
    get: function (r) { return r.pcodes; },
    test: function (r, s) { for (var i = 0; i < s.vals.length; i++) if (r.pset.has(s.vals[i])) return true; return false; } };
  function topicMode(params) { return params.tmode === "all" || params.tmode === "primary" ? params.tmode : "any"; }
  var EFACETS = [
    facet("syllabus", "Syllabus", single(function (e) { return e.sy || "none"; }), { lab: sylLabel }),
    facet("session", "Session", single(function (e) { return e.session; }), { order: ["May", "November"] }),
    facet("tz", "Time zone", single(function (e) { return e.tz || "none"; }), { order: TZ_ORDER.concat("none"), lab: tzLabel }),
    facet("paper", "Paper", single(function (e) { return e.paper; }), { order: PAPER_ORDER, lab: function (v) { return "Paper " + v; } }),
    facet("option", "Paper 3 option", single(function (e) { return e.optSlug || "none"; }), { lab: optLabel, last: "none" }),
    facet("level", "Level", single(function (e) { return e.level || "none"; }), { order: ["HL", "SL", "HLSL", "none"], lab: function (v) { return LEVEL_NAMES[v] || v; } }),
    facet("status", "Extraction", single(function (e) { return e.status; }), { order: STATUS_ORDER, lab: function (v) { return STATUS_NAMES[v] || v; } })
  ];
  function sylLabel(v) { return v === "none" ? "Unspecified" : (DB.sylNames[v] || v); }
  function tzLabel(v) { return v === "none" ? "No time zone" : v; }
  function optLabel(v) { return v === "none" ? "Not an option paper" : (DB.optNames[v] || v); }

  // With dedupe, questions of one duplicate group (r.gk) count once per facet value, so every count equals the
  // length of the list you get by ticking that value (lists keep the preferred member of each group, dedupeRows).
  function runFacets(items, pred, facets, sel, dedupe) {
    var n = facets.length, active = [], counts = [], out = [], i;
    var seen = dedupe ? new Set() : null;
    for (i = 0; i < n; i++) { active.push(!!sel[facets[i].p]); counts.push(new Map()); }
    for (var j = 0; j < items.length; j++) {
      var r = items[j];
      if (pred && !pred(r)) continue;
      var fails = 0, fi = -1;
      for (i = 0; i < n; i++) {
        if (active[i] && !facets[i].test(r, sel[facets[i].p])) { fails++; fi = i; if (fails > 1) break; }
      }
      if (fails > 1) continue;
      var g = seen && r.gk;
      if (fails === 0) { out.push(r); for (i = 0; i < n; i++) tally(counts[i], facets[i].get(r), g, i, seen); }
      else tally(counts[fi], facets[fi].get(r), g, fi, seen);
    }
    var cm = {};
    facets.forEach(function (f, k) { cm[f.p] = counts[k]; });
    return { rows: dedupe ? dedupeRows(out) : out, all: out, counts: cm };
  }
  function tally(m, v, g, fi, seen) {
    var i;
    if (!g) {
      if (Array.isArray(v)) { for (i = 0; i < v.length; i++) m.set(v[i], (m.get(v[i]) || 0) + 1); }
      else m.set(v, (m.get(v) || 0) + 1);
      return;
    }
    if (!Array.isArray(v)) v = [v];
    for (i = 0; i < v.length; i++) {
      var key = fi + "\u0001" + v[i] + "\u0001" + g;
      if (seen.has(key)) continue;
      seen.add(key);
      m.set(v[i], (m.get(v[i]) || 0) + 1);
    }
  }
  // keep one question per duplicate group: the best-ranked member present in the list
  function dedupeRows(rows) {
    var best = new Map(), any = false;
    rows.forEach(function (r) { if (r.gk) { any = true; var b = best.get(r.gk); if (!b || r.dr < b.dr) best.set(r.gk, r); } });
    return any ? rows.filter(function (r) { return !r.gk || best.get(r.gk) === r; }) : rows;
  }
  function dupHidden(params, view) {
    if (params.dup === "hide") return true;
    if (params.dup === "show") return false;
    return !!DUP_DEFAULT[view];
  }
  // the dup parameter to put on a link to `view` so that it shows what the current view shows
  function dupFor(hidden, view) { return hidden === !!DUP_DEFAULT[view] ? "" : (hidden ? "hide" : "show"); }
  function removedShown(params) { return params.removed === "show"; }
  var valueCache = new Map();
  function facetValues(scopeKey, items, f) {
    var key = scopeKey + "|" + f.p;
    if (valueCache.has(key)) return valueCache.get(key);
    var seen = new Set();
    items.forEach(function (r) { var v = f.get(r); if (Array.isArray(v)) v.forEach(function (x) { seen.add(x); }); else seen.add(v); });
    var vals = Array.from(seen);
    vals.sort(function (a, b) {
      if (f.order) return idx(f.order, a) - idx(f.order, b) || collator.compare(a, b);
      if (f.last) { if (a === f.last) return 1; if (b === f.last) return -1; }
      return collator.compare(f.lab ? f.lab(a) : a, f.lab ? f.lab(b) : b);
    });
    valueCache.set(key, vals);
    return vals;
  }
  function selection(params, facets) {
    var sel = {};
    facets.forEach(function (f) {
      var v = list(params, f.p);
      if (f.alias) v = v.map(f.alias);
      if (f.topic) v = v.concat(list(params, "sub"));
      if (v.length) sel[f.p] = { set: new Set(v), vals: v, mode: topicMode(params) };
    });
    return sel;
  }

  // ---------------------------------------------------------------- sorting
  var QCOLS = {
    id: { label: "ID", key: function (r) { return r.idRank; } },
    subject: { label: "Subject", key: function (r) { return r.S.ord; } },
    year: { label: "Year", key: function (r) { return r.ex.year; }, dir: -1, num: true },
    session: { label: "Session", key: function (r) { return r.ex.sessIdx; } },
    tz: { label: "TZ", key: function (r) { return r.ex.tz ? r.ex.tzIdx : null; } },
    paper: { label: "Paper", key: function (r) { return r.ex.paperIdx; } },
    option: { label: "Option", key: function (r) { return r.ex.optRank; } },
    q: { label: "Q", key: function (r) { return r.numKey; }, num: true, title: "Question number" },
    section: { label: "Sec.", key: function (r) { return r.sec ? r.sec.charCodeAt(0) : null; }, title: "Section" },
    marks: { label: "Marks", key: function (r) { return r.marks; }, num: true },
    type: { label: "Type", key: function (r) { return r.typeIdx; } },
    topics: { label: "Topics", key: function (r) { return r.topicKey == null ? null : r.S.ord * 100000 + r.topicKey; } },
    answer: { label: "Answer", key: function (r) { return idx(ANS_ORDER, r.ans); }, title: "Markscheme status" },
    exam: { label: "Exam", key: function (r) { return r.ex.ord; }, hidden: true }
  };
  var QCOL_ORDER = ["id", "subject", "year", "session", "tz", "paper", "option", "q", "section", "marks", "type", "topics", "answer"];
  var ECOLS = {
    id: { label: "Exam ID", key: function (e) { return e.idRank; } },
    subject: { label: "Subject", key: function (e) { return e.S.ord; } },
    syllabus: { label: "Syllabus", key: function (e) { return e.sy || null; } },
    year: { label: "Year", key: function (e) { return e.year; }, dir: -1, num: true },
    session: { label: "Session", key: function (e) { return e.sessIdx; } },
    tz: { label: "TZ", key: function (e) { return e.tz ? e.tzIdx : null; } },
    paper: { label: "Paper", key: function (e) { return e.paperIdx; } },
    option: { label: "Option", key: function (e) { return e.optRank; } },
    level: { label: "Level", key: function (e) { return e.level || null; } },
    questions: { label: "Qs", key: function (e) { return e.qs.length; }, num: true, title: "Questions extracted" },
    marks: { label: "Marks", key: function (e) { return e.marks || null; }, num: true },
    ms: { label: "MS", key: function (e) { return e.hasMs ? 0 : 1; }, title: "Markscheme found" },
    status: { label: "Status", key: function (e) { return idx(STATUS_ORDER, e.status); } }
  };
  var ECOL_ORDER = ["id", "subject", "syllabus", "year", "session", "tz", "paper", "option", "level", "questions", "marks", "ms", "status"];

  function parseSort(s, cols) {
    var out = [], seen = {};
    String(s || "").split(",").forEach(function (part) {
      var kv = part.split(":"), k = kv[0];
      if (!cols[k] || cols[k].hidden || seen[k]) return;
      seen[k] = 1;
      out.push({ k: k, d: kv[1] === "desc" ? -1 : 1 });
    });
    return out;
  }
  function sortStr(spec) { return spec.map(function (s) { return s.k + ":" + (s.d < 0 ? "desc" : "asc"); }).join(","); }
  function sortItems(items, spec, cols) {
    if (!spec.length) return items;
    var fns = spec.map(function (s) { return cols[s.k].key; }), dirs = spec.map(function (s) { return s.d; });
    var n = fns.length;
    var dec = items.map(function (r) {
      var a = new Array(n + 1);
      for (var i = 0; i < n; i++) { var v = fns[i](r); a[i] = v === undefined ? null : v; }
      a[n] = r;
      return a;
    });
    dec.sort(function (x, y) {
      for (var i = 0; i < n; i++) {
        var a = x[i], b = y[i];
        if (a === b) continue;
        if (a == null) return 1;
        if (b == null) return -1;
        return (a < b ? -1 : 1) * dirs[i];
      }
      return x[n].ord - y[n].ord;
    });
    return dec.map(function (a) { return a[n]; });
  }

  // ---------------------------------------------------------------- question query (cached)
  var GROUPS = {
    none: { label: "None" },
    subject: { label: "Subject", col: "subject", dir: 1, key: function (r) { return r.S.ord; }, name: function (r) { return r.S.name; } },
    year: { label: "Year", col: "year", dir: -1, key: function (r) { return r.ex.year; }, name: function (r) { return String(r.ex.year); } },
    exam: { label: "Exam", col: "exam", dir: 1, key: function (r) { return r.ex.ord; }, name: function (r) { return examTitle(r.ex, true); } },
    paper: { label: "Paper", col: "paper", dir: 1, key: function (r) { return r.S.ord * 100 + r.ex.paperIdx; }, name: function (r, multi) { return (multi ? r.S.short + ", " : "") + "Paper " + r.ex.paper; } },
    topic: { label: "Primary topic", col: "topics", dir: 1, key: function (r) { return r.topicKey == null ? r.S.ord * 100000 + 99999 : r.S.ord * 100000 + r.topicKey; },
      name: function (r, multi) {
        var pre = multi ? r.S.short + " " : "";
        if (!r.tp.length) return pre + "Unclassified";
        return pre + r.tp[0] + " " + codeName(r.S, r.tp[0]);
      } }
  };
  var qcache = { key: null, res: null };
  // view: which view asks (decides whether repeated questions are hidden when the address does not say)
  function questionQuery(params, view) {
    var hideDup = dupHidden(params, view || "questions"), showRemoved = removedShown(params);
    var key = JSON.stringify(pick(params, FILTER_KEYS.concat(["sort", "group"]))) + "|" + hideDup;
    if (qcache.key === key) return qcache.res;
    var subj = validSubject(params.subject);
    var S = subj ? DB.byId[subj] : null;
    var base = S ? S.rows : DB.rows;
    var yr = parseRange(params.year), mk = parseRange(params.marks);
    var exl = list(params, "exam"), exSet = exl.length ? new Set(exl) : null;
    var terms = parseSearch(params.q), where = params["in"] === "q" || params["in"] === "ms" ? params["in"] : "";
    var test = function (r) {
      if (yr && (r.ex.year < yr[0] || r.ex.year > yr[1])) return false;
      if (mk && (r.marks == null || r.marks < mk[0] || r.marks > mk[1])) return false;
      if (exSet && !exSet.has(r.ex.id)) return false;
      if (terms.length && !matchSearch(r, terms, where)) return false;
      return true;
    };
    var plainPred = yr || mk || exSet || terms.length ? test : null;
    var pred = showRemoved ? plainPred : function (r) { return !r.removed && (!plainPred || plainPred(r)); };
    var facets = QFACETS.filter(function (f) { return !f.topic || S; });
    if (S && topicMode(params) === "primary") facets = facets.map(function (f) { return f.topic ? PRIMARY_TOPIC_FACET : f; });
    var sel = selection(params, facets);
    var fr = runFacets(base, pred, facets, sel, hideDup);
    // removed-for-copyright questions that the other filters would let through (shown next to the toggle)
    var removedN = 0;
    base.forEach(function (r) {
      if (!r.removed || (plainPred && !plainPred(r))) return;
      for (var i = 0; i < facets.length; i++) if (sel[facets[i].p] && !facets[i].test(r, sel[facets[i].p])) return;
      removedN++;
    });
    var spec = parseSort(params.sort, QCOLS);
    var g = GROUPS[params.group] && params.group !== "none" ? params.group : "";
    var full = spec.slice();
    if (g) {
      var G = GROUPS[g];
      var d = spec.length && spec[0].k === G.col ? spec[0].d : G.dir;
      if (G.col !== "exam") full = full.filter(function (s) { return s.k !== G.col; });
      full.unshift({ k: "_g", d: d });
    }
    var cols = QCOLS;
    if (g) { cols = Object.create(QCOLS); cols._g = { key: GROUPS[g].key }; }
    var rows = sortItems(fr.rows, full, cols);
    var groups = null;
    if (g) {
      groups = new Map();
      rows.forEach(function (r) { var k = GROUPS[g].key(r); groups.set(k, (groups.get(k) || 0) + 1); });
    }
    var res = { rows: rows, counts: fr.counts, base: base, S: S, subj: subj, facets: facets, sel: sel,
      terms: terms, where: where, spec: spec, group: g, groups: groups, marks: 0,
      hideDup: hideDup, showRemoved: showRemoved, removedN: removedN,
      // hideDup: repeats left out; otherwise: how many rows are repeats of another row in this list
      repeats: hideDup ? fr.all.length - fr.rows.length : fr.rows.length - dedupeRows(fr.rows).length };
    rows.forEach(function (r) { res.marks += r.marks || 0; });
    qcache.key = key; qcache.res = res;
    return res;
  }

  // ---------------------------------------------------------------- router
  var CUR = { view: null, arg: null, params: {} };
  var lastQuestionsHash = "#/questions";
  var main = null;
  var pendingFocus = null;   // "first" | "last" row after a page change
  var scrollResults = false;

  var routedHash = null;
  function go(hash, replace) {
    if (replace) history.replaceState(null, "", hash);
    else if (location.hash !== hash) history.pushState(null, "", hash);
    route();
  }
  function onHistory() { if (location.hash !== routedHash) route(); }
  function setParams(changes, keepPage) {
    var p = assign(CUR.params, changes);
    if (!keepPage) delete p.page;
    go(hashOf(CUR.view, CUR.arg, p));
  }

  var VIEWS = {
    questions: viewQuestions, q: viewQuestion, papers: viewPapers, paper: viewPaper,
    topics: viewTopics, practice: viewPractice, help: viewHelp
  };
  function route() {
    var rt = parseHash();
    routedHash = location.hash;
    if (!VIEWS[rt.view]) { history.replaceState(null, "", hashOf("questions", "", rt.view ? {} : rt.params)); rt = parseHash(); routedHash = location.hash; }
    var changed = rt.view !== CUR.view || rt.arg !== CUR.arg;
    var viewChanged = rt.view !== CUR.view;
    CUR = rt;
    if (rt.view === "questions") lastQuestionsHash = location.hash || "#/questions";
    $$(".nav a").forEach(function (a) {
      var v = a.getAttribute("data-nav");
      var cur = v === rt.view || (v === "questions" && rt.view === "q") || (v === "papers" && rt.view === "paper");
      if (cur) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
      if (v === "questions") a.setAttribute("href", lastQuestionsHash);
      if (v === "practice" && rt.view !== "practice") a.setAttribute("href", hashOf("practice", "", pick(parseHashStr(lastQuestionsHash).params, FILTER_KEYS)));
    });
    if (viewChanged) main.removeAttribute("data-view");
    try { VIEWS[rt.view](rt); }
    catch (err) { main.innerHTML = "<p class=\"error\">" + esc(err && err.message || err) + "</p>"; if (window.console) console.error(err); }
    if (changed) {
      window.scrollTo(0, 0);
      var ae = document.activeElement;
      if (viewChanged && (!ae || ae === document.body || !document.contains(ae) || !main.contains(ae))) main.focus({ preventScroll: true });
    }
    if (pendingFocus === "search") { pendingFocus = null; var sb = $("#qsearch") || $("#psearch"); if (sb) sb.focus(); }
  }
  function title(t) { document.title = t ? t + " - " + APP : APP; }
  function shell(name, html) {
    if (main.getAttribute("data-view") === name) return false;
    main.setAttribute("data-view", name);
    main.innerHTML = html;
    return true;
  }

  // ---------------------------------------------------------------- shared sidebar
  function preserveFocus(container, fn) {
    var a = document.activeElement, id = a && container.contains(a) ? a.id : null;
    var st = container.scrollTop;
    fn();
    container.scrollTop = st;
    if (id) { var el = document.getElementById(id); if (el) el.focus({ preventScroll: true }); }
  }
  var treeOpen = {};   // subject|topic -> expanded (UI state only)

  function checkGroup(f, vals, counts, selSet, showZero) {
    var h = "";
    vals.forEach(function (v) {
      var c = counts ? (counts.get(v) || 0) : null, on = selSet && selSet.has(v);
      if (!showZero && c === 0 && !on) return;
      var id = "f-" + f.p + "-" + idSafe(v);
      h += "<label class=\"ck" + (c === 0 ? " zero" : "") + "\" for=\"" + id + "\"><input type=\"checkbox\" id=\"" + id +
        "\" data-p=\"" + f.p + "\" value=\"" + esc(v) + "\"" + (on ? " checked" : "") + "><span class=\"t\">" +
        esc(f.lab ? f.lab(v) : v) + "</span>" + (c == null ? "" : "<span class=\"n\">" + fmt(c) + "</span>") + "</label>";
    });
    return h;
  }
  function facetFieldset(f, vals, counts, selSet) {
    if (vals.length < 2 && !(selSet && selSet.size)) return "";
    return "<fieldset class=\"fg\"><legend>" + esc(f.label) + "</legend>" + checkGroup(f, vals, counts, selSet, true) + "</fieldset>";
  }
  function subjectSelect(params, allowAll, counter) {
    var subj = validSubject(params.subject);
    var h = "<fieldset class=\"fg\"><legend>Subject</legend><label class=\"vh\" for=\"f-subject\">Subject</label>" +
      "<select id=\"f-subject\" class=\"full\" data-p=\"subject\">";
    if (allowAll) h += "<option value=\"\">All subjects (" + fmt(counter(null)) + ")</option>";
    DB.list.forEach(function (S) {
      h += "<option value=\"" + esc(S.id) + "\"" + (S.id === subj ? " selected" : "") + ">" + esc(S.name) + " (" + fmt(counter(S)) + ")</option>";
    });
    return h + "</select></fieldset>";
  }
  function rangeFieldset(p, label, params, years) {
    var r = parseRange(params[p]);
    var lo = r && r[0] !== -Infinity ? r[0] : "", hi = r && r[1] !== Infinity ? r[1] : "";
    var h = "<fieldset class=\"fg\"><legend>" + esc(label) + "</legend><div class=\"row2\">";
    if (years) {
      var opts = function (sel) {
        return "<option value=\"\">any</option>" + years.map(function (y) { return "<option" + (y === sel ? " selected" : "") + ">" + y + "</option>"; }).join("");
      };
      h += "<label for=\"f-" + p + "-lo\">From</label><select id=\"f-" + p + "-lo\" data-range=\"" + p + "\">" + opts(lo) + "</select>" +
        "<label for=\"f-" + p + "-hi\">to</label><select id=\"f-" + p + "-hi\" data-range=\"" + p + "\">" + opts(hi) + "</select>";
    } else {
      h += "<label for=\"f-" + p + "-lo\">From</label><input type=\"number\" min=\"0\" inputmode=\"numeric\" id=\"f-" + p + "-lo\" data-range=\"" + p + "\" value=\"" + lo + "\">" +
        "<label for=\"f-" + p + "-hi\">to</label><input type=\"number\" min=\"0\" inputmode=\"numeric\" id=\"f-" + p + "-hi\" data-range=\"" + p + "\" value=\"" + hi + "\">";
    }
    return h + "</div></fieldset>";
  }
  // Repeats (the same question in several papers) and questions removed for copyright: explicit toggles.
  function repeatFieldset(res, view) {
    var defHidden = !!DUP_DEFAULT[view];
    var h = "<fieldset class=\"fg\"><legend>Repeated and removed questions</legend>" +
      "<label class=\"ck\" for=\"f-dup\" title=\"Some papers were set in two time zones with the same questions, or reuse a question verbatim. Ticked: each such question is listed once.\">" +
      "<input type=\"checkbox\" id=\"f-dup\"" + (res && res.hideDup ? " checked" : "") + "><span class=\"t\">Hide repeated questions</span>" +
      (res ? "<span class=\"n\">" + fmt(res.repeats) + "</span>" : "") + "</label>" +
      "<label class=\"ck\" for=\"f-removed\" title=\"Questions whose text was removed from the published paper for copyright reasons; only their markscheme remains.\">" +
      "<input type=\"checkbox\" id=\"f-removed\"" + (res && res.showRemoved ? " checked" : "") + "><span class=\"t\">Include questions removed for copyright</span>" +
      (res ? "<span class=\"n\">" + fmt(res.removedN) + "</span>" : "") + "</label>";
    if (res) {
      h += "<p class=\"note\" id=\"dupnote\">" + (res.hideDup ? plural(res.repeats, "repeated copy", "repeated copies") + " left out, so each question is counted once" :
        plural(res.repeats, "listed question is a copy", "listed questions are copies") + " of another listed question") +
        " (repeats are " + (defHidden ? "hidden" : "shown") + " by default here).</p>";
    }
    return h + "</fieldset>";
  }
  function topicTree(S, counts, params) {
    var sel = new Set(list(params, "topic").concat(list(params, "sub")));
    var mode = topicMode(params);
    var c = function (code) { return counts ? (counts.get(code) || 0) : null; };
    var cnt = function (code) { var n = c(code); return n == null ? "" : "<span class=\"n" + (n ? "" : " zero") + "\">" + fmt(n) + "</span>"; };
    var radio = function (v, label, tip) {
      return "<label title=\"" + esc(tip) + "\"><input type=\"radio\" name=\"tmode\" id=\"f-tmode-" + v + "\" value=\"" + v + "\"" + (mode === v ? " checked" : "") + "> " + label + "</label>";
    };
    var h = "<fieldset class=\"fg\"><legend>Topics</legend>" +
      "<div class=\"tmode row2\" role=\"radiogroup\" aria-label=\"Topic match mode\">Match" +
      radio("any", "any", "Questions that cover any ticked topic, as main or secondary topic") +
      radio("all", "all", "Questions that cover every ticked topic") +
      radio("primary", "main topic", "Questions whose main (first-listed) topic or subtopic is ticked; each question has one") + "</div>" +
      "<label class=\"vh\" for=\"f-tfilter\">Find a topic</label><input type=\"search\" id=\"f-tfilter\" class=\"full\" placeholder=\"Find a topic\" autocomplete=\"off\">" +
      "<ul class=\"tree\" id=\"f-tree\">";
    S.tax.forEach(function (T) {
      var key = S.id + "|" + T.code;
      var anySub = T.subs.some(function (U) { return sel.has(U.code); });
      var open = treeOpen[key] != null ? treeOpen[key] : anySub;
      var id = "f-topic-" + idSafe(T.code), lid = "f-sub-list-" + idSafe(T.code);
      h += "<li data-name=\"" + esc((T.code + " " + T.name).toLowerCase()) + "\"><div class=\"tr\">" +
        (T.subs.length ? "<button type=\"button\" class=\"tw\" id=\"f-tw-" + idSafe(T.code) + "\" data-key=\"" + esc(key) + "\" aria-expanded=\"" + open + "\" aria-controls=\"" + lid +
          "\" title=\"Show subtopics\"><span aria-hidden=\"true\">" + (open ? "&minus;" : "+") + "</span><span class=\"vh\">Subtopics of " + esc(T.code) + "</span></button>" : "<span class=\"tw ph\"></span>") +
        "<label for=\"" + id + "\"><input type=\"checkbox\" id=\"" + id + "\" data-p=\"topic\" value=\"" + esc(T.code) + "\"" + (sel.has(T.code) ? " checked" : "") + ">" +
        "<span class=\"code\">" + esc(T.code) + "</span> " + esc(T.name) + "</label>" + cnt(T.code) + "</div>";
      if (T.subs.length) {
        h += "<ul id=\"" + lid + "\"" + (open ? "" : " hidden") + ">";
        T.subs.forEach(function (U) {
          var uid = "f-sub-" + idSafe(U.code);
          h += "<li data-name=\"" + esc((U.code + " " + U.name).toLowerCase()) + "\"><div class=\"tr\"><label for=\"" + uid + "\"><input type=\"checkbox\" id=\"" + uid + "\" data-p=\"sub\" value=\"" + esc(U.code) + "\"" +
            (sel.has(U.code) ? " checked" : "") + "><span class=\"code\">" + esc(U.code) + "</span> " + esc(U.name) + "</label>" + cnt(U.code) + "</div></li>";
        });
        h += "</ul>";
      }
      h += "</li>";
    });
    h += "<li data-name=\"unclassified\"><div class=\"tr\"><span class=\"tw ph\"></span><label for=\"f-topic-none\"><input type=\"checkbox\" id=\"f-topic-none\" data-p=\"topic\" value=\"none\"" +
      (sel.has("none") ? " checked" : "") + ">Unclassified</label>" + cnt("none") + "</div></li></ul></fieldset>";
    return h;
  }

  function bindFilterForm(form) {
    form.addEventListener("submit", function (e) { e.preventDefault(); });
    form.addEventListener("change", function (e) {
      var t = e.target;
      if (t.id === "f-tfilter") return;
      if (t.name === "tmode") { setParams({ tmode: t.value === "all" || t.value === "primary" ? t.value : "" }); return; }
      if (t.id === "f-dup") { setParams({ dup: dupFor(t.checked, CUR.view) }); return; }
      if (t.id === "f-removed") { setParams({ removed: t.checked ? "show" : "" }); return; }
      var range = t.getAttribute("data-range");
      if (range) {
        var lo = $("#f-" + range + "-lo", form).value.trim(), hi = $("#f-" + range + "-hi", form).value.trim();
        setParams((function () { var o = {}; o[range] = rangeStr(lo, hi); return o; })());
        return;
      }
      var p = t.getAttribute("data-p");
      if (!p) return;
      var o = {};
      if (t.type === "checkbox") {
        var cur = list(CUR.params, p).filter(function (v) { return v !== t.value; });
        if (t.checked) cur.push(t.value);
        o[p] = cur.join(",");
      } else {
        o[p] = t.value;
        if (p === "subject") { o.topic = ""; o.sub = ""; o.syllabus = ""; o.option = ""; o.exam = ""; o.cols = ""; }
      }
      setParams(o);
    });
    form.addEventListener("click", function (e) {
      var tw = e.target.closest("button.tw");
      if (tw) {
        var open = tw.getAttribute("aria-expanded") !== "true";
        treeOpen[tw.getAttribute("data-key")] = open;
        tw.setAttribute("aria-expanded", String(open));
        tw.firstChild.innerHTML = open ? "&minus;" : "+";
        var ul = document.getElementById(tw.getAttribute("aria-controls"));
        if (ul) ul.hidden = !open;
        return;
      }
      var clr = e.target.closest("[data-clear]");
      if (clr) {
        var keep = pick(CUR.params, ["sort", "per", "group", "n", "seed", "ms", "rows", "cols", "tcount"]);
        if (CUR.view === "topics") keep.subject = CUR.params.subject;
        go(hashOf(CUR.view, CUR.arg, keep));
      }
    });
    form.addEventListener("input", function (e) {
      if (e.target.id !== "f-tfilter") return;
      filterTree(form, e.target.value);
    });
  }
  function filterTree(form, q) {
    q = q.trim().toLowerCase();
    $$("#f-tree > li", form).forEach(function (li) {
      var subs = $$("ul > li", li), anySub = false;
      subs.forEach(function (s) { var m = !q || s.getAttribute("data-name").indexOf(q) >= 0; s.hidden = !m; if (m && q) anySub = true; });
      var self = !q || li.getAttribute("data-name").indexOf(q) >= 0;
      li.hidden = !(self || anySub);
      var ul = $("ul", li);
      if (ul) {
        if (q && anySub) ul.hidden = false;
        else if (!q) ul.hidden = $("button.tw", li).getAttribute("aria-expanded") !== "true";
        if (q && self && !anySub) subs.forEach(function (s) { s.hidden = false; });
      }
    });
  }

  function chipsHtml(params, opts) {
    var chips = [], S = DB.byId[validSubject(params.subject)];
    var add = function (p, v, label, val) {
      chips.push("<span class=\"chip\"><span><b>" + esc(label) + ":</b> " + esc(val) + "</span>" +
        (opts && opts.fixed ? "" : "<button type=\"button\" data-rm=\"" + esc(p) + "\" data-v=\"" + esc(v) + "\" aria-label=\"Remove filter " + esc(label + " " + val) + "\">&times;</button>") + "</span>");
    };
    if (S && !(opts && opts.noSubject)) add("subject", "", "Subject", S.name);
    list(params, "exam").forEach(function (v) { var ex = DB.examById.get(v); add("exam", v, "Exam", ex ? examShort(ex) : v); });
    var yr = parseRange(params.year);
    if (yr) add("year", "", "Year", (yr[0] === -Infinity ? "up to " : yr[0]) + (yr[0] === yr[1] ? "" : (yr[0] === -Infinity ? "" : "–") + (yr[1] === Infinity ? " onwards" : yr[1])));
    QFACETS.forEach(function (f) {
      if (f.topic) return;
      list(params, f.p).forEach(function (v) { add(f.p, v, f.label, f.lab ? f.lab(v) : v); });
    });
    var mk = parseRange(params.marks);
    if (mk) add("marks", "", "Marks", (mk[0] === -Infinity ? "up to " : mk[0]) + (mk[0] === mk[1] ? "" : (mk[0] === -Infinity ? "" : "–") + (mk[1] === Infinity ? " or more" : mk[1])));
    if (S) {
      var tl = list(params, "topic"), sl = list(params, "sub");
      var tm = topicMode(params);
      var mode = tm === "primary" ? " (main)" : tm === "all" && tl.length + sl.length > 1 ? " (all)" : "";
      tl.forEach(function (v) { add("topic", v, "Topic" + mode, v === "none" ? "Unclassified" : v + " " + codeName(S, v)); });
      sl.forEach(function (v) { add("sub", v, "Subtopic" + mode, v + " " + codeName(S, v)); });
    }
    if (params.q) add("q", "", params["in"] === "q" ? "Text (question)" : params["in"] === "ms" ? "Text (markscheme)" : "Text", params.q);
    // only when different from what the view does by default
    var view = opts && opts.view || CUR.view;
    if ((params.dup === "hide" || params.dup === "show") && dupHidden(params, view) !== !!DUP_DEFAULT[view]) {
      add("dup", "", "Repeated questions", params.dup === "hide" ? "hidden" : "included");
    }
    if (removedShown(params)) add("removed", "", "Removed for copyright", "included");
    return chips.join("");
  }
  function filterText(params) {
    var d = document.createElement("div");
    d.innerHTML = chipsHtml(params, { fixed: true });
    return $$(".chip > span", d).map(function (s) { return s.textContent; }).join("; ");
  }
  function bindChips(el) {
    el.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-rm]");
      if (!b) return;
      var p = b.getAttribute("data-rm"), v = b.getAttribute("data-v"), o = {};
      if (v) o[p] = list(CUR.params, p).filter(function (x) { return x !== v; }).join(",");
      else o[p] = "";
      if (p === "subject") { o.topic = ""; o.sub = ""; o.syllabus = ""; o.option = ""; }
      if (p === "q") o["in"] = "";
      setParams(o);
      var next = $("#chips button");
      if (next) next.focus(); else { var s = $("#qsearch"); if (s) s.focus(); }
    });
  }

  // ---------------------------------------------------------------- tables
  function thead(cols, order, spec, sortable) {
    var h = "<thead><tr>";
    order.forEach(function (k) {
      var c = cols[k], pos = -1;
      spec.forEach(function (s, i) { if (s.k === k) pos = i; });
      var aria = pos === 0 ? (spec[0].d < 0 ? "descending" : "ascending") : null;
      var ind = pos >= 0 ? (spec[pos].d < 0 ? "&darr;" : "&uarr;") + (spec.length > 1 ? (pos + 1) : "") : "";
      h += "<th scope=\"col\"" + (c.num ? " class=\"num\"" : "") + (aria ? " aria-sort=\"" + aria + "\"" : "") + ">";
      if (sortable) {
        h += "<button type=\"button\" data-sort=\"" + k + "\"" + (c.title ? " title=\"" + esc(c.title) + "\"" : "") + ">" + esc(c.label) +
          "<span class=\"si\" aria-hidden=\"true\">" + ind + "</span>" +
          (pos >= 0 ? "<span class=\"vh\">, sorted " + (spec[pos].d < 0 ? "descending" : "ascending") + (spec.length > 1 ? ", priority " + (pos + 1) : "") + "</span>" : "") + "</button>";
      } else h += esc(c.label);
      h += "</th>";
    });
    return h + "</tr></thead>";
  }
  function nextSort(spec, k, shift, cols) {
    var i = -1;
    spec.forEach(function (s, j) { if (s.k === k) i = j; });
    var def = cols[k].dir || 1;
    if (!shift) {
      if (i === 0 && spec.length === 1) return [{ k: k, d: -spec[0].d }];
      if (i === 0) return [{ k: k, d: -spec[0].d }].concat(spec.slice(1));
      return [{ k: k, d: def }];
    }
    var out = spec.slice();
    if (i < 0) out.push({ k: k, d: def });
    else if (out[i].d === def) out[i] = { k: k, d: -def };
    else out.splice(i, 1);
    return out;
  }
  function pagerHtml(total, page, per, mk, label) {
    var pages = Math.max(1, Math.ceil(total / per));
    var a = total ? (page - 1) * per + 1 : 0, b = Math.min(total, page * per);
    var link = function (p, text, rel) {
      if (p < 1 || p > pages || p === page) return "<span class=\"off\" aria-disabled=\"true\">" + text + "</span>";
      return "<a class=\"btn\" href=\"" + mk(p) + "\" data-page=\"" + p + "\"" + (rel ? " rel=\"" + rel + "\"" : "") + ">" + text + "</a>";
    };
    return "<nav class=\"pager\" aria-label=\"" + esc(label) + "\">" + link(1, "First") + link(page - 1, "Previous", "prev") +
      "<label>Page <input type=\"number\" min=\"1\" max=\"" + pages + "\" value=\"" + page + "\" data-goto=\"1\" aria-label=\"Page number\"> of " + fmt(pages) + "</label>" +
      link(page + 1, "Next", "next") + link(pages, "Last") +
      "<span class=\"range\">" + (total ? fmt(a) + "&ndash;" + fmt(b) + " of " + fmt(total) : "no results") + "</span></nav>";
  }
  function bindTableNav(container, cols, defPer) {
    container.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-sort]");
      if (b) {
        var spec = parseSort(CUR.params.sort, cols);
        var ns = nextSort(spec, b.getAttribute("data-sort"), e.shiftKey, cols);
        var k = b.getAttribute("data-sort");
        setParams({ sort: sortStr(ns) }, false);
        var nb = container.querySelector("button[data-sort=\"" + k + "\"]");
        if (nb) nb.focus();
        return;
      }
      var a = e.target.closest("a[data-page]");
      if (a && a.closest(".pager") && a.closest(".pager").parentNode.lastElementChild === a.closest(".pager")) scrollResults = true;
    });
    container.addEventListener("change", function (e) {
      var t = e.target;
      if (t.getAttribute("data-goto")) {
        var max = +t.max || 1, v = clamp(parseInt(t.value, 10) || 1, 1, max);
        setParams({ page: v > 1 ? String(v) : "" }, true);
      } else if (t.id === "group") setParams({ group: t.value === "none" ? "" : t.value });
      else if (t.id === "per") setParams({ per: +t.value === defPer ? "" : t.value });
      else if (t.id === "qin") setParams({ "in": t.value });
    });
  }
  function getPer(params, def) { var v = parseInt(params.per, 10); return PER_PAGE.indexOf(v) >= 0 ? v : def; }

  function topicCell(r) {
    if (!r.tp.length) return "<span class=\"zero\">&ndash;</span>";
    var parts = [];
    r.tp.forEach(function (t) {
      var subs = r.su.filter(function (s) { var c = r.S.codes.get(s); return c && c.parent && c.parent.code === t; });
      if (subs.length) parts = parts.concat(subs); else parts.push(t);
    });
    var tip = r.tp.map(function (t) { return t + " " + codeName(r.S, t); }).concat(r.su.map(function (s) { return s + " " + codeName(r.S, s); })).join("\n");
    return "<span title=\"" + esc(tip) + "\">" + esc(parts.join(", ")) + "</span>";
  }

  // questions in a subject (or all) as the lists count them: removed-for-copyright ones only when included
  function visibleCount(S, p) {
    var rows = S ? S.rows : DB.rows;
    if (removedShown(p)) return rows.length;
    var n = 0;
    for (var i = 0; i < rows.length; i++) if (!rows[i].removed) n++;
    return n;
  }
  function tagsCell(r) {
    if (!r.tags.length) return "";
    return "<div class=\"tags\">" + r.tags.map(function (t) { return "<span class=\"tag\" title=\"" + esc(t[1]) + "\">" + esc(t[0]) + "</span>"; }).join(" ") + "</div>";
  }

  // ---------------------------------------------------------------- Questions view
  function viewQuestions(rt) {
    var p = rt.params;
    title("Questions");
    var created = shell("questions",
      "<div class=\"layout\">" +
      "<aside class=\"side no-print\" aria-label=\"Filters\"><details class=\"fbox\" id=\"fbox\" open><summary>Filters</summary>" +
      "<form class=\"filters\" id=\"filters\" autocomplete=\"off\"></form></details></aside>" +
      "<section class=\"content\" aria-labelledby=\"h-q\"><h1 id=\"h-q\">Questions</h1>" +
      "<div class=\"searchbar\" role=\"search\"><label class=\"vh\" for=\"qsearch\">Search question and markscheme text</label>" +
      "<input type=\"search\" id=\"qsearch\" placeholder=\"Search text (press / to focus)\" autocomplete=\"off\" spellcheck=\"false\">" +
      "<label class=\"vh\" for=\"qin\">Search in</label><select id=\"qin\"><option value=\"\">Question and markscheme</option><option value=\"q\">Question only</option><option value=\"ms\">Markscheme only</option></select></div>" +
      "<div class=\"chips\" id=\"chips\"></div><div id=\"results\"></div></section></div>");
    var form = $("#filters"), results = $("#results"), search = $("#qsearch");
    if (created) {
      if (window.matchMedia("(max-width: 860px)").matches) $("#fbox").open = false;
      bindFilterForm(form);
      bindChips($("#chips"));
      bindTableNav(main.querySelector(".content"), QCOLS, 50);
      var push = debounce(function () { if (CUR.view === "questions") setParams({ q: search.value.trim() }); }, 300);
      search.addEventListener("input", push);
      search.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); setParams({ q: search.value.trim() }); } });
    }
    if (document.activeElement !== search && search.value.trim() !== (p.q || "")) search.value = p.q || "";
    $("#qin").value = p["in"] === "q" || p["in"] === "ms" ? p["in"] : "";
    $("#chips").innerHTML = chipsHtml(p);

    var subj = validSubject(p.subject), scope = subjectsFor(subj);
    if (parseSearch(p.q).length && !textReady(scope)) {
      results.innerHTML = "<p class=\"status\" role=\"status\">Loading question text for search&hellip;</p>";
      renderQSidebar(form, null, p);
      ensureText(scope).then(function () { if (CUR.view === "questions") route(); },
        function (err) { results.innerHTML = "<p class=\"error\">Could not load question text: " + esc(err.message) + "</p>"; });
      return;
    }
    var res = questionQuery(p, "questions");
    renderQSidebar(form, res, p);
    renderQResults(results, res, p);
  }

  // Table cells show the option's first word ("Series", "Discrete", ...); the full name is in the tooltip.
  function optCell(ex) {
    if (!ex.option) return "<td></td>";
    return "<td title=\"" + esc(ex.option) + "\">" + esc(ex.option.split(/\s+/)[0]) + "</td>";
  }

  function renderQSidebar(form, res, p) {
    var subj = validSubject(p.subject), S = DB.byId[subj];
    var base = S ? S.rows : DB.rows, scopeKey = "q:" + (subj || "*");
    var h = subjectSelect(p, true, function (X) { return visibleCount(X, p); });
    h += repeatFieldset(res, "questions");
    h += rangeFieldset("year", "Year", p, (S ? yearsOf(S.exams) : DB.years));
    QFACETS.forEach(function (f) {
      if (f.topic) return;
      var vals = facetValues(scopeKey, base, f);
      h += facetFieldset(f, vals, res ? res.counts[f.p] : null, res && res.sel[f.p] ? res.sel[f.p].set : new Set(list(p, f.p)));
    });
    h += rangeFieldset("marks", "Marks", p, null);
    if (S) h += topicTree(S, res ? res.counts.topic : null, p);
    else h += "<fieldset class=\"fg\"><legend>Topics</legend><p class=\"note\">Choose a subject to filter by topic.</p></fieldset>";
    h += "<div class=\"actions\"><button type=\"button\" data-clear=\"1\">Clear all filters</button></div>";
    preserveFocus(form.closest(".side"), function () {
      var tf = $("#f-tfilter", form), tq = tf ? tf.value : "";
      form.innerHTML = h;
      if (tq && $("#f-tfilter", form)) { $("#f-tfilter", form).value = tq; filterTree(form, tq); }
    });
  }
  function yearsOf(exams) {
    var ys = {};
    exams.forEach(function (e) { ys[e.year] = 1; });
    return Object.keys(ys).map(Number).sort(function (a, b) { return a - b; });
  }

  function listParams(p) { var o = pick(p, FILTER_KEYS.concat(["sort", "group", "per"])); return o; }
  function qHref(r, lp) { return hashOf("q", r.id, lp); }

  function renderQResults(el, res, p) {
    var per = getPer(p, 50), total = res.rows.length;
    var pages = Math.max(1, Math.ceil(total / per));
    var page = clamp(parseInt(p.page, 10) || 1, 1, pages);
    var lp = listParams(p);
    var mk = function (n) { return hashOf("questions", "", assign(p, { page: n > 1 ? String(n) : "" })); };
    var multi = !res.subj;
    var h = "<div class=\"toolbar\"><span class=\"count\" role=\"status\" aria-live=\"polite\">" + plural(total, "question") +
      (total ? " &middot; " + plural(res.marks, "mark") : "") + "</span>" +
      (res.repeats ? "<span class=\"dupinfo\">" + (res.hideDup ? plural(res.repeats, "repeated question") + " hidden" :
        "includes " + plural(res.repeats, "repeated question") ) +
        " <button type=\"button\" class=\"linkish\" id=\"duptoggle\">" + (res.hideDup ? "Show repeats" : "Hide repeats") + "</button></span>" : "") +
      "<label>Group by <select id=\"group\">" + Object.keys(GROUPS).map(function (g) {
        if (g === "subject" && !multi) return "";
        return "<option value=\"" + g + "\"" + ((res.group || "none") === g ? " selected" : "") + ">" + esc(GROUPS[g].label) + "</option>";
      }).join("") + "</select></label>" +
      "<label>Rows per page <select id=\"per\">" + PER_PAGE.map(function (n) { return "<option" + (n === per ? " selected" : "") + ">" + n + "</option>"; }).join("") + "</select></label>" +
      "<a href=\"" + hashOf("practice", "", pick(p, FILTER_KEYS)) + "\">Practice set from these results</a>" +
      "<button type=\"button\" id=\"csv\"" + (total ? "" : " disabled") + ">Download CSV</button></div>";
    if (!DB.rows.length) {
      el.innerHTML = h + "<p class=\"empty\">No questions have been extracted yet. The <a href=\"#/papers\">Papers</a> list shows every catalogued exam.</p>";
      bindCsv(res);
      return;
    }
    h += pagerHtml(total, page, per, mk, "Pagination, top");
    var scopeKey = "q:" + (res.subj || "*");
    var hasVal = function (p) { var f = QFACETS.filter(function (x) { return x.p === p; })[0]; return facetValues(scopeKey, res.base, f).some(function (v) { return v !== "none"; }); };
    var show = { subject: multi, option: hasVal("option"), section: hasVal("section"), tz: hasVal("tz") };
    var order = QCOL_ORDER.filter(function (k) { return show[k] !== false; });
    var on = function (k) { return show[k] !== false; };
    var cols = order.length;
    var t = "<div class=\"tablewrap\"><table class=\"grid\" id=\"qtable\"><caption class=\"vh\">Questions, sorted by " +
      (res.spec.length ? res.spec.map(function (s) { return QCOLS[s.k].label + (s.d < 0 ? " descending" : " ascending"); }).join(", then ") : "exam order") +
      "</caption>" + thead(QCOLS, order, res.spec, true) + "<tbody>";
    var start = (page - 1) * per, end = Math.min(total, start + per), lastG = null, G = res.group ? GROUPS[res.group] : null;
    for (var i = start; i < end; i++) {
      var r = res.rows[i], ex = r.ex;
      if (G) {
        var gk = G.key(r);
        if (gk !== lastG) {
          t += "<tr class=\"grp\"><th colspan=\"" + cols + "\" scope=\"colgroup\">" + esc(G.name(r, multi)) +
            " <span class=\"n\">" + plural(res.groups.get(gk), "question") + (lastG === null && i > 0 && G.key(res.rows[i - 1]) === gk ? ", continued" : "") + "</span></th></tr>";
          lastG = gk;
        }
      }
      var snip = res.terms.length ? snippet(r, res.terms, res.where) : "";
      t += "<tr" + (snip ? " class=\"has-snip\"" : "") + "><td><a class=\"qid" + (r.id.length > 30 ? " long" : "") + "\" href=\"" + qHref(r, lp) + "\">" + esc(r.id) + "</a>" + tagsCell(r) + "</td>" +
        (on("subject") ? "<td>" + esc(r.S.short) + "</td>" : "") + "<td class=\"num\">" + ex.year + "</td><td>" + (ex.session === "November" ? "Nov" : "May") + "</td>" +
        (on("tz") ? "<td>" + esc(ex.tz || "") + "</td>" : "") + "<td>" + esc(ex.paper) + "</td>" + (on("option") ? optCell(ex) : "") +
        "<td class=\"num\">" + esc(r.num) + "</td>" + (on("section") ? "<td>" + esc(r.sec || "") + "</td>" : "") + "<td class=\"num\">" + (r.marks == null ? "" : r.marks) + "</td>" +
        "<td>" + esc(r.type || "") + "</td><td>" + topicCell(r) + "</td>" +
        "<td class=\"ans-" + esc(r.ans) + "\">" + esc(ANS_NAMES[r.ans] || r.ans) + "</td></tr>";
      if (snip) t += "<tr class=\"snip\"><td></td><td colspan=\"" + (cols - 1) + "\">" + snip + "</td></tr>";
    }
    if (!total) t += "<tr><td colspan=\"" + cols + "\" class=\"empty\">No questions match these filters.</td></tr>";
    t += "</tbody></table></div>";
    el.innerHTML = h + t + pagerHtml(total, page, per, mk, "Pagination, bottom");
    bindCsv(res);
    var dt = $("#duptoggle");
    if (dt) dt.addEventListener("click", function () { setParams({ dup: dupFor(!res.hideDup, "questions") }); var b = $("#duptoggle"); if (b) b.focus(); });
    if (scrollResults) { scrollResults = false; var tb = $("#qtable"); if (tb && tb.getBoundingClientRect().top < 0) tb.scrollIntoView(); }
    if (pendingFocus) {
      var links = $$("a.qid", el);
      var target = pendingFocus === "last" ? links[links.length - 1] : links[0];
      pendingFocus = null;
      if (target) target.focus();
    }
  }
  function bindCsv(res) {
    var b = $("#csv");
    if (!b) return;
    b.onclick = function () {
      var head = ["id", "subject", "syllabus", "year", "session", "tz", "paper", "option", "question", "section", "marks", "type", "topics", "subtopics", "markscheme", "mcq_answer", "flags", "also_in", "transcribed", "review_note"];
      var q = function (v) { v = v == null ? "" : String(v); return /[",\n]/.test(v) ? "\"" + v.replace(/"/g, "\"\"") + "\"" : v; };
      var lines = [head.join(",")];
      res.rows.forEach(function (r) {
        var ex = r.ex;
        lines.push([r.id, r.S.id, ex.sy, ex.year, ex.session, ex.tz, ex.paper, ex.option, r.num, r.sec, r.marks, r.type,
          r.tp.join(" "), r.su.join(" "), r.ans, r.mcq, r.flags.join(" "), r.dups.map(function (d) { return d.id; }).join(" "),
          r.clean ? "yes" : "no", r.note].map(q).join(","));
      });
      var blob = new Blob([lines.join("\n") + "\n"], { type: "text/csv" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "questions.csv";
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
    };
  }

  // ---------------------------------------------------------------- Question detail
  var showMs = false;
  function imageHtml(ex, name, size, alt) {
    if (!name) return "";
    return "<div class=\"imgbox\"><img class=\"pageimg\" src=\"" + imgUrl(ex, name) + "\" alt=\"" + esc(alt) + "\"" +
      (size ? " width=\"" + size[0] + "\" height=\"" + size[1] + "\"" : "") + " loading=\"lazy\" decoding=\"async\"></div>";
  }
  function hasFlag(r, f) { return r.flags.indexOf(f) >= 0; }
  function noticeHtml(kind, head, body, tag) {
    tag = tag || "div";
    return "<" + tag + " class=\"notice n-" + kind + "\" role=\"note\"><strong>" + esc(head) + ".</strong> " + body + "</" + tag + ">";
  }
  // Shown next to the official answer: the key is believed to be wrong and the note says why.
  function disputedHtml(r) {
    return "<div class=\"notice n-disputed\" role=\"note\"><p class=\"nh\"><strong>Answer key disputed.</strong> " +
      (r.mcq ? "The answer above is the official key, which is believed to be wrong." : "The official answer is believed to be wrong.") + "</p>" +
      (r.note ? richHtml(r.note, false, "p") : "") + "</div>";
  }
  function msHtml(r, headingTag, headingText) {
    var h = headingTag ? "<" + headingTag + ">" + esc(headingText || "Markscheme") + "</" + headingTag + ">" : "";
    if (r.mcq) h += "<p class=\"mcq\">Answer: <strong>" + esc(r.mcq) + "</strong>" + (r.disputed ? " <span class=\"keynote\">(official key, disputed)</span>" : "") + "</p>";
    if (r.disputed) h += disputedHtml(r);
    if (r.msImg) h += imageHtml(r.ex, r.msImg, r.mz, "Markscheme for question " + r.num);
    else if (r.mstext && !(r.mcq && r.mstext.trim().length <= 3)) h += "<pre class=\"text\">" + esc(r.mstext) + "</pre>";
    else if (!r.mcq) h += "<p class=\"noimg\">" + (r.S.textState !== "ready" && r.ans !== "missing" ? "Markscheme image not available; extracted text not loaded." : "No markscheme available for this question.") + "</p>";
    if (r.ans === "suspect") h += "<p class=\"warn\">The markscheme match for this question is uncertain.</p>";
    return h;
  }
  // Notices about the source shown above a question (question page: full; paper and practice lists: short).
  function sourceNotices(r) {
    var h = "";
    if (r.removed) h += noticeHtml("removed", "Removed for copyright", "This question is missing from the published paper for copyright reasons; " +
      (r.msImg || r.mstext ? "only its markscheme remains." : "no usable content remains."));
    else if (r.partRemoved) h += noticeHtml("partial", "Content removed for copyright", "Part of this question (for example a text extract or a figure) is missing from the published paper for copyright reasons.");
    if (hasFlag(r, "source-incomplete")) h += noticeHtml("incomplete", "Source incomplete", "The available copy of the paper is missing part of this question.");
    if (hasFlag(r, "crop-bad")) h += noticeHtml("crop", "Image crop faulty", "The page image may be cut off or include material from a neighbouring question" + (r.clean ? "; the transcription follows the paper." : "."));
    return h;
  }
  function questionImage(r) {
    if (r.img) return imageHtml(r.ex, r.img, r.iz, "Question " + r.num + " as printed in the paper");
    if (r.text && r.clean) return "<div class=\"transbox\">" + richHtml(r.text, true) + "</div>";
    if (r.text) return "<pre class=\"text\">" + esc(r.text) + "</pre>";
    return "<p class=\"noimg\">No image available for this question.</p>";
  }
  function tagsHtml(r) {
    if (!r.tp.length) return "<p class=\"note\">Not yet classified.</p>";
    var h = "<ul class=\"taglist\">";
    r.tp.forEach(function (t, k) {
      h += "<li><a href=\"" + hashOf("questions", "", { subject: r.S.id, topic: t }) + "\"><span class=\"code\">" + esc(t) + "</span>" + esc(codeName(r.S, t)) + "</a>" +
        (k === 0 && r.tp.length > 1 ? " <span class=\"note\">(main)</span>" : "");
      var subs = r.su.filter(function (s) { var c = r.S.codes.get(s); return c && c.parent && c.parent.code === t; });
      if (subs.length) {
        h += "<ul>" + subs.map(function (s) {
          return "<li><a href=\"" + hashOf("questions", "", { subject: r.S.id, sub: s }) + "\"><span class=\"code\">" + esc(s) + "</span>" + esc(codeName(r.S, s)) + "</a></li>";
        }).join("") + "</ul>";
      }
      h += "</li>";
    });
    return h + "</ul>";
  }
  function alsoHtml(r) {
    if (!r.dups.length) return "";
    return "<h2>Also appeared as</h2><ul class=\"also\">" + r.dups.map(function (d) {
      return "<li><a href=\"" + hashOf("q", d.id, {}) + "\">" + esc(examTitle(d.ex)) + ", question " + esc(d.num) + "</a></li>";
    }).join("") + "</ul><p class=\"note\">The same question was set in " + (r.dups.length === 1 ? "another paper" : "other papers") +
      ". Lists can hide repeats so that it is counted once.</p>";
  }
  function flagsHtml(r) {
    // a question removed entirely also carries content-removed; one entry is enough
    var shown = r.flags.filter(function (f) { return FLAG_INFO[f] && !(r.removed && f === "content-removed"); });
    var other = r.flags.filter(function (f) { return !FLAG_INFO[f]; });
    if (!shown.length && !other.length) return "";
    return "<h2>Flags</h2><ul class=\"flags\">" + shown.map(function (f) {
      return "<li class=\"fl-" + esc(f) + "\"><span class=\"fn\">" + esc(FLAG_INFO[f].label) + "</span> <span class=\"note\">" + esc(FLAG_INFO[f].desc) + "</span></li>";
    }).join("") + other.map(function (f) { return "<li><span class=\"fn\">" + esc(f) + "</span></li>"; }).join("") + "</ul>";
  }
  function noteHtml(r) {
    if (!r.note) return "";
    if (r.disputed) return "";
    return "<h2>Reviewer note</h2>" + richHtml(r.note, false, "p");
  }
  function qviewMode(r) {
    if (!r.clean) return "image";
    if (!r.img) return "text";
    return prefs.qview;
  }
  function viewQuestion(rt) {
    shell("q-" + rt.arg, "");
    var r = DB.rowById.get(rt.arg);
    if (!r) {
      title("Question not found");
      main.innerHTML = "<h1>Question not found</h1><p>No question has the ID <code>" + esc(rt.arg) + "</code>. <a href=\"" + lastQuestionsHash + "\">Back to questions</a></p>";
      return;
    }
    var ex = r.ex, p = rt.params, lp = listParams(p);
    title(r.id);
    if (r.S.textState === "none" && (r.clean || !r.img || (!r.msImg && !r.mcq))) {
      ensureText([r.S]).then(function () { if (CUR.view === "q" && CUR.arg === r.id) route(); }, function () {});
    }
    var nav = "", pos = null, prev = null, next = null;
    var scope = subjectsFor(validSubject(p.subject));
    var needText = parseSearch(p.q).length && !textReady(scope);
    if (!needText) {
      var res = questionQuery(p, "q");
      var i = res.rows.indexOf(r);
      if (i >= 0) {
        pos = i; prev = res.rows[i - 1] || null; next = res.rows[i + 1] || null;
        var per = getPer(p, 50), pg = Math.floor(i / per) + 1;
        nav = "<a href=\"" + hashOf("questions", "", assign(lp, { page: pg > 1 ? String(pg) : "" })) + "\">Back to results</a>" +
          "<span class=\"pos\">" + fmt(i + 1) + " of " + fmt(res.rows.length) + "</span>" +
          (prev ? "<a href=\"" + qHref(prev, lp) + "\" rel=\"prev\" id=\"prev\">Previous (k)</a>" : "<span class=\"off\">Previous</span>") +
          (next ? "<a href=\"" + qHref(next, lp) + "\" rel=\"next\" id=\"next\">Next (j)</a>" : "<span class=\"off\">Next</span>");
      } else {
        nav = "<a href=\"" + hashOf("questions", "", lp) + "\">Back to results</a><span class=\"pos\">Not in the current result list" +
          (r.removed && !removedShown(p) ? " (questions removed for copyright are hidden)" : r.gk && dupHidden(p, "q") ? " (repeats are hidden)" : "") + "</span>";
      }
    } else {
      nav = "<span class=\"pos\">Loading result list&hellip;</span>";
      ensureText(scope).then(function () { if (CUR.view === "q" && CUR.arg === r.id) route(); }, function () {});
    }
    var meta = [
      ["Subject", esc(r.S.name)],
      ["Syllabus", esc(sylLabel(ex.sy || "none"))],
      ["Paper", "<a href=\"" + hashOf("paper", ex.id, { at: r.num }) + "\">" + esc(examTitle(ex)) + "</a>"],
      ["Exam ID", "<code>" + esc(ex.id) + "</code>"],
      ["Question", esc(r.num) + (r.sec ? ", Section " + esc(r.sec) : "")],
      ["Marks", r.marks == null ? "&ndash;" : esc(r.marks)],
      ["Type", esc(r.type ? QTYPE_NAMES[r.type] || r.type : "–")],
      ["Markscheme", "<span class=\"ans-" + esc(r.ans) + "\">" + esc(ANS_NAMES[r.ans] || r.ans) + "</span>" + (r.disputed ? " <span class=\"ans-suspect\">(key disputed)</span>" : "")],
      ["Text", r.clean ? "Checked transcription" : "Automatic extraction"]
    ];
    if (ex.level) meta.splice(2, 0, ["Level", esc(LEVEL_NAMES[ex.level] || ex.level)]);
    var mode = qviewMode(r);
    var sw = r.clean && r.img ? "<span class=\"seg\" role=\"group\" aria-label=\"Show\">" + [["both", "Image and transcription"], ["image", "Page image"], ["text", "Transcription"]].map(function (o) {
      return "<button type=\"button\" data-qview=\"" + o[0] + "\" aria-pressed=\"" + (mode === o[0]) + "\">" + o[1] + "</button>";
    }).join("") + "</span>" : "";
    var trans = "";
    if (r.clean) {
      trans = "<section class=\"trans\" aria-labelledby=\"h-trans\"><h2 id=\"h-trans\">Transcription</h2>" +
        "<div class=\"transbox\" id=\"transbody\">" + (r.text != null ? richHtml(r.text, true) : "<p class=\"status\">Loading text&hellip;</p>") + "</div>" +
        "<p class=\"note\">Typed from the paper: maths as in print, figures described in square brackets." + (r.img ? " The page image is the original." : "") + "</p></section>";
    }
    var body = r.img || r.clean ? "<div id=\"qbody\" data-mode=\"" + mode + "\">" +
      (r.img ? "<div class=\"qimg\">" + imageHtml(ex, r.img, r.iz, "Question " + r.num + " as printed in the paper") + "</div>" : "") + trans + "</div>"
      : questionImage(r);
    var h = "<nav class=\"crumbs no-print\" aria-label=\"Result navigation\">" + nav + "</nav>" +
      "<h1>Question " + esc(r.num) + " <span class=\"sub\">&ndash; " + esc(examTitle(ex, true)) + "</span></h1>" +
      "<div class=\"detail\"><div class=\"dmain\">" + sourceNotices(r) +
      (sw ? "<div class=\"toolbar no-print\">" + sw + "</div>" : "") + body +
      "<div class=\"actions no-print\"><button type=\"button\" id=\"msbtn\" aria-pressed=\"" + showMs + "\" aria-controls=\"mssec\">Markscheme (m)</button>" +
      "<button type=\"button\" id=\"copyq\"" + (r.clean ? " title=\"Copies the transcription, with maths as LaTeX\"" : "") + ">Copy question text</button><button type=\"button\" id=\"copym\">Copy markscheme text</button>" +
      "<span class=\"msg\" id=\"copymsg\" role=\"status\"></span></div>" +
      "<section class=\"mssec\" id=\"mssec\"" + (showMs ? "" : " hidden") + " aria-label=\"Markscheme\">" + msHtml(r, "h2") + "</section>" +
      "<details class=\"text\" id=\"textbox\"><summary>" + (r.clean ? "Markscheme text (automatic extraction)" : "Extracted text (automatic, may contain errors)") + "</summary><div id=\"textbody\"></div></details>" +
      "</div><aside aria-label=\"Question details\"><h2>Details</h2><table class=\"kv\"><tbody>" +
      meta.map(function (m) { return "<tr><th scope=\"row\">" + m[0] + "</th><td>" + m[1] + "</td></tr>"; }).join("") +
      "</tbody></table>" + flagsHtml(r) + noteHtml(r) + alsoHtml(r) + "<h2>Topics</h2>" + tagsHtml(r) +
      "<p class=\"note\">ID <code>" + esc(r.id) + "</code></p></aside></div>";
    main.innerHTML = h;
    upgradeTex(main);
    $("#msbtn").addEventListener("click", toggleMs);
    $$("button[data-qview]").forEach(function (b) {
      b.addEventListener("click", function () {
        prefs.qview = b.getAttribute("data-qview");
        savePrefs();
        $("#qbody").setAttribute("data-mode", prefs.qview);
        $$("button[data-qview]").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
      });
    });
    var fillText = function () {
      var tb = $("#textbody");
      if (!tb) return;
      var msPart = r.mstext ? "<pre class=\"text\">" + esc(r.mstext) + "</pre>" : "<p class=\"note\">No extracted markscheme text.</p>";
      tb.innerHTML = r.clean ? msPart : "<h3>Question</h3>" + (r.text ? "<pre class=\"text\">" + esc(r.text) + "</pre>" : "<p class=\"note\">No extracted text.</p>") +
        "<h3>Markscheme</h3>" + msPart;
    };
    var withText = function (fn) {
      if (r.S.textState === "ready") { fn(); return; }
      $("#copymsg").textContent = "Loading text…";
      ensureText([r.S]).then(function () { $("#copymsg").textContent = ""; fn(); }, function (err) { $("#copymsg").textContent = "Could not load text: " + err.message; });
    };
    $("#textbox").addEventListener("toggle", function () { if (this.open) withText(fillText); });
    $("#copyq").addEventListener("click", function () { withText(function () { copy(r.text, "Question text"); }); });
    $("#copym").addEventListener("click", function () {
      withText(function () { copy(r.mstext || (r.mcq ? "Answer: " + r.mcq : null), "Markscheme text"); });
    });
  }
  function copy(text, what) {
    var msg = $("#copymsg");
    if (!text) { msg.textContent = "No " + what.toLowerCase() + " available."; return; }
    var done = function () { msg.textContent = what + " copied."; };
    var fallback = function () {
      var ta = document.createElement("textarea");
      ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      ta.remove();
      msg.textContent = ok ? what + " copied." : "Copy failed; select the text on the page instead.";
    };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, fallback);
    else fallback();
  }
  function toggleMs() {
    showMs = !showMs;
    var b = $("#msbtn"), s = $("#mssec");
    if (b) b.setAttribute("aria-pressed", String(showMs));
    if (s) { s.hidden = !showMs; if (showMs && s.getBoundingClientRect().top > window.innerHeight) s.scrollIntoView({ block: "start" }); }
  }

  // ---------------------------------------------------------------- Papers list
  function viewPapers(rt) {
    var p = rt.params;
    title("Papers");
    var created = shell("papers",
      "<div class=\"layout\"><aside class=\"side no-print\" aria-label=\"Filters\"><details class=\"fbox\" id=\"fbox\" open><summary>Filters</summary>" +
      "<form class=\"filters\" id=\"filters\" autocomplete=\"off\"></form></details></aside>" +
      "<section class=\"content\" aria-labelledby=\"h-p\"><h1 id=\"h-p\">Papers</h1>" +
      "<div class=\"searchbar\" role=\"search\"><label class=\"vh\" for=\"psearch\">Find exam by ID, file name or paper code</label>" +
      "<input type=\"search\" id=\"psearch\" placeholder=\"Find by exam ID, file name or paper code (press /)\" autocomplete=\"off\" spellcheck=\"false\"></div>" +
      "<div class=\"chips\" id=\"chips\"></div><div id=\"results\"></div></section></div>");
    var form = $("#filters"), search = $("#psearch");
    if (created) {
      if (window.matchMedia("(max-width: 860px)").matches) $("#fbox").open = false;
      bindFilterForm(form);
      bindChips($("#chips"));
      bindTableNav(main.querySelector(".content"), ECOLS, 100);
      var push = debounce(function () { if (CUR.view === "papers") setParams({ q: search.value.trim() }); }, 250);
      search.addEventListener("input", push);
    }
    if (document.activeElement !== search && search.value.trim() !== (p.q || "")) search.value = p.q || "";
    var subj = validSubject(p.subject), S = DB.byId[subj];
    var base = S ? S.exams : DB.exams;
    var yr = parseRange(p.year), q = (p.q || "").toLowerCase().trim();
    var pred = (yr || q) ? function (e) {
      if (yr && (e.year < yr[0] || e.year > yr[1])) return false;
      if (q) {
        var hay = (e.id + " " + (e.src || "") + " " + (e.mss || "") + " " + (e.code || "") + " " + (e.pnum || "")).toLowerCase();
        var words = q.split(/\s+/);
        for (var i = 0; i < words.length; i++) if (hay.indexOf(words[i]) < 0) return false;
      }
      return true;
    } : null;
    var sel = selection(p, EFACETS);
    var fr = runFacets(base, pred, EFACETS, sel);
    var spec = parseSort(p.sort, ECOLS);
    var rows = sortItems(fr.rows, spec, ECOLS);
    // sidebar
    var scopeKey = "e:" + (subj || "*");
    var h = subjectSelect(p, true, function (X) { return X ? X.exams.length : DB.exams.length; });
    h += rangeFieldset("year", "Year", p, S ? yearsOf(S.exams) : DB.years);
    EFACETS.forEach(function (f) { h += facetFieldset(f, facetValues(scopeKey, base, f), fr.counts[f.p], sel[f.p] ? sel[f.p].set : null); });
    h += "<div class=\"actions\"><button type=\"button\" data-clear=\"1\">Clear all filters</button></div>";
    preserveFocus(form.closest(".side"), function () { form.innerHTML = h; });
    // chips
    var chips = [];
    if (S) chips.push(["subject", "", "Subject", S.name]);
    if (yr) chips.push(["year", "", "Year", p.year]);
    EFACETS.forEach(function (f) { list(p, f.p).forEach(function (v) { chips.push([f.p, v, f.label, f.lab ? f.lab(v) : v]); }); });
    if (p.q) chips.push(["q", "", "Find", p.q]);
    $("#chips").innerHTML = chips.map(function (c) {
      return "<span class=\"chip\"><span><b>" + esc(c[2]) + ":</b> " + esc(c[3]) + "</span><button type=\"button\" data-rm=\"" + esc(c[0]) + "\" data-v=\"" + esc(c[1]) + "\" aria-label=\"Remove filter " + esc(c[2] + " " + c[3]) + "\">&times;</button></span>";
    }).join("");
    // table
    var per = getPer(p, 100), total = rows.length, pages = Math.max(1, Math.ceil(total / per));
    var page = clamp(parseInt(p.page, 10) || 1, 1, pages);
    var mk = function (n) { return hashOf("papers", "", assign(p, { page: n > 1 ? String(n) : "" })); };
    var nq = 0, ext = 0;
    rows.forEach(function (e) { nq += e.qs.length; if (e.status !== "unprocessed") ext++; });
    var out = "<div class=\"toolbar\"><span class=\"count\" role=\"status\" aria-live=\"polite\">" + plural(total, "paper") + " &middot; " + fmt(ext) + " extracted &middot; " + plural(nq, "question") + "</span>" +
      "<label>Rows per page <select id=\"per\">" + PER_PAGE.map(function (n) { return "<option" + (n === per ? " selected" : "") + ">" + n + "</option>"; }).join("") + "</select></label></div>";
    out += pagerHtml(total, page, per, mk, "Pagination, top");
    var eOpt = facetValues(scopeKey, base, EFACETS[4]).some(function (v) { return v !== "none"; });
    var eorder = ECOL_ORDER.filter(function (k) { return (k !== "subject" || !S) && (k !== "option" || eOpt); });
    var has = function (k) { return eorder.indexOf(k) >= 0; };
    out += "<div class=\"tablewrap\"><table class=\"grid\" id=\"ptable\"><caption class=\"vh\">Papers</caption>" + thead(ECOLS, eorder, spec, true) + "<tbody>";
    for (var i = (page - 1) * per; i < Math.min(total, page * per); i++) {
      var e = rows[i];
      out += "<tr><td><a class=\"qid" + (e.id.length > 30 ? " long" : "") + "\" href=\"" + hashOf("paper", e.id, {}) + "\">" + esc(e.id) + "</a></td>" + (has("subject") ? "<td>" + esc(e.S.short) + "</td>" : "") +
        "<td title=\"" + esc(e.sy ? sylLabel(e.sy) : "") + "\">" + esc(e.sy ? DB.sylShort[e.sy] || e.sy : "") + "</td>" +
        "<td class=\"num\">" + e.year + "</td><td>" + (e.session === "November" ? "Nov" : "May") + "</td><td>" + esc(e.tz || "") + "</td><td>" + esc(e.paper) + "</td>" +
        (has("option") ? optCell(e) : "") + "<td>" + esc(e.level || "") + "</td><td class=\"num\">" + (e.status === "unprocessed" ? "" : fmt(e.qs.length)) + "</td>" +
        "<td class=\"num\">" + (e.marks ? fmt(e.marks) : "") + "</td><td>" + (e.hasMs ? "yes" : "<span class=\"ans-missing\">no</span>") + "</td>" +
        "<td class=\"st-" + esc(e.status) + "\">" + esc(STATUS_NAMES[e.status] || e.status) + "</td></tr>";
    }
    if (!total) out += "<tr><td colspan=\"" + eorder.length + "\" class=\"empty\">No papers match these filters.</td></tr>";
    out += "</tbody></table></div>" + pagerHtml(total, page, per, mk, "Pagination, bottom");
    var results = $("#results");
    results.innerHTML = out;
    if (scrollResults) { scrollResults = false; var tb = $("#ptable"); if (tb && tb.getBoundingClientRect().top < 0) tb.scrollIntoView(); }
    if (pendingFocus) {
      var links = $$("a.qid", results), target = pendingFocus === "last" ? links[links.length - 1] : links[0];
      pendingFocus = null;
      if (target) target.focus();
    }
  }

  // ---------------------------------------------------------------- Paper detail
  function msModeOf(p) { return p.ms === "inline" || p.ms === "end" ? p.ms : ""; }
  var lastMsMode = "inline";
  function viewPaper(rt) {
    var ex = DB.examById.get(rt.arg), p = rt.params;
    if (main.getAttribute("data-view") !== "paper") main.removeAttribute("data-arg");
    main.setAttribute("data-view", "paper");
    if (!ex) {
      title("Paper not found");
      main.innerHTML = "<h1>Paper not found</h1><p>No exam has the ID <code>" + esc(rt.arg) + "</code>. <a href=\"#/papers\">All papers</a></p>";
      return;
    }
    title(examShort(ex));
    var mode = msModeOf(p);
    if (mode) lastMsMode = mode;
    var meta = [
      ["Exam ID", "<code>" + esc(ex.id) + "</code>"],
      ["Subject", esc(ex.S.name)], ["Syllabus", esc(sylLabel(ex.sy || "none"))],
      ["Session", esc(ex.session + " " + ex.year)], ["Paper", esc(ex.paper) + (ex.option ? " &ndash; " + esc(ex.option) : "")],
      ["Time zone", esc(ex.tz || "none")], ["Level", esc(LEVEL_NAMES[ex.level] || ex.level || "–")],
      ["Status", "<span class=\"st-" + esc(ex.status) + "\">" + esc(STATUS_NAMES[ex.status] || ex.status) + "</span>"]
    ];
    if (ex.status !== "unprocessed") meta.push(["Questions", fmt(ex.qs.length) + (ex.marks ? " (" + plural(ex.marks, "mark") + ")" : "")]);
    if (ex.pages) meta.push(["Question paper pages", fmt(ex.pages)]);
    if (ex.code) meta.push(["Paper code", "<code>" + esc(ex.code) + "</code>"]);
    if (ex.pnum) meta.push(["Paper number", esc(ex.pnum)]);
    if (ex.src) meta.push(["Source file", "<code>" + esc(ex.src) + "</code>"]);
    meta.push(["Markscheme file", ex.mss ? "<code>" + esc(ex.mss) + "</code>" : "<span class=\"ans-missing\">none found</span>"]);
    if (ex.notes) meta.push(["Notes", linkExamIds(ex.notes)]);
    var shared = new Map();
    ex.qs.forEach(function (r) { r.dups.forEach(function (d) { if (d.ex !== ex) shared.set(d.ex, (shared.get(d.ex) || 0) + 1); }); });
    if (shared.size) {
      meta.push(["Shared questions", Array.from(shared.entries()).sort(function (a, b) { return a[0].ord - b[0].ord; }).map(function (kv) {
        return (kv[1] === ex.qs.length ? "All " + fmt(kv[1]) : fmt(kv[1]) + " of " + fmt(ex.qs.length)) + " questions also appear in <a href=\"" +
          hashOf("paper", kv[0].id, {}) + "\">" + esc(examTitle(kv[0], kv[0].S !== ex.S)) + "</a>";
      }).join("<br>")]);
    }
    var h = "<nav class=\"crumbs no-print\" aria-label=\"Breadcrumb\"><a href=\"#/papers\">All papers</a>" +
      (ex.qs.length ? "<a href=\"" + hashOf("questions", "", { subject: ex.S.id, exam: ex.id }) + "\">These questions in the question list</a>" : "") + "</nav>" +
      "<div class=\"paper-head\"><h1>" + esc(examTitle(ex, true)) + "</h1><table class=\"kv\"><tbody>" +
      meta.map(function (m) { return "<tr><th scope=\"row\">" + m[0] + "</th><td>" + m[1] + "</td></tr>"; }).join("") + "</tbody></table></div>";
    if (!ex.qs.length) {
      h += "<p class=\"empty\">" + (ex.status === "unprocessed" ? "This paper has not been extracted yet." :
        ex.status === "failed" ? "Extraction failed for this paper; no questions are available." : "No questions were extracted from this paper.") + "</p>";
      main.innerHTML = h;
      return;
    }
    h += "<div class=\"toolbar no-print\"><span>Markscheme:</span><span class=\"seg\" role=\"group\" aria-label=\"Markscheme display\">" +
      [["", "Hidden"], ["inline", "Under each question"], ["end", "At the end"]].map(function (o) {
        return "<button type=\"button\" data-ms=\"" + o[0] + "\" aria-pressed=\"" + (mode === o[0]) + "\">" + o[1] + "</button>";
      }).join("") + "</span><button type=\"button\" id=\"print\">Print</button>" +
      "<span class=\"note\">Keys: j / k next / previous question, m markscheme.</span></div>";
    if (ex.status === "partial") h += "<p class=\"warn\">Some questions of this paper could not be extracted; the list below is incomplete.</p>";
    h += questionBlocks(ex.qs, mode, function (r) { return "Question " + r.num; }, true, false, { subject: ex.S.id, exam: ex.id });
    var same = main.getAttribute("data-arg") === ex.id;
    main.setAttribute("data-arg", ex.id);
    if (same) keepAnchor(function () { main.innerHTML = h; }); else main.innerHTML = h;
    upgradeTex(main);
    if (ex.S.textState === "none" && ex.qs.some(function (r) { return !r.img || (!r.msImg && !r.mcq); })) {
      ensureText([ex.S]).then(function () { if (CUR.view === "paper" && CUR.arg === ex.id) route(); }, function () {});
    }
    bindPrintAndMs();
    if (p.at && !same) {
      var target = document.getElementById("q-" + idSafe(p.at));
      if (target) { target.scrollIntoView(); var hd = $(".qhead", target); if (hd) hd.focus({ preventScroll: true }); }
    }
  }
  function keepAnchor(fn) {
    var blocks = $$(".qblock[id]"), anchor = null, off = 0;
    for (var i = 0; i < blocks.length; i++) {
      var b = blocks[i].getBoundingClientRect();
      if (b.bottom > 0) { anchor = blocks[i].id; off = b.top; break; }
    }
    fn();
    if (anchor) { var el = document.getElementById(anchor); if (el) window.scrollBy(0, el.getBoundingClientRect().top - off); }
  }
  function linkExamIds(text) {
    return esc(text).replace(/\b((?:math|physics|economics)-\d{4}-[MN]-P[0-9AB]+(?:-[a-z-]+?)?(?:-TZ\d)?)\b/g, function (m) {
      return DB.examById.has(m) ? "<a href=\"" + hashOf("paper", m, {}) + "\">" + m + "</a>" : m;
    });
  }
  function questionBlocks(rows, mode, headFn, sections, numbered, linkParams) {
    var h = "<ol class=\"qlist\">", lastSec = null;
    rows.forEach(function (r, i) {
      if (sections && r.sec && r.sec !== lastSec) { h += "<li class=\"secth\"><h2 class=\"secthead\">Section " + esc(r.sec) + "</h2></li>"; lastSec = r.sec; }
      var meta = [];
      if (r.marks != null) meta.push(plural(r.marks, "mark"));
      if (r.type) meta.push(r.type);
      if (r.tp.length) meta.push((r.su.length ? r.su : r.tp).join(", "));
      var also = sections ? r.dups.filter(function (d) { return d.ex !== r.ex; }).map(function (d) {
        return "<a class=\"also\" href=\"" + hashOf("q", d.id, {}) + "\">also " + esc(examShort(d.ex)) + " Q" + esc(d.num) + "</a>";
      }).join("") : "";
      h += "<li class=\"qblock" + (r.removed ? " removed" : "") + "\" id=\"q-" + idSafe(numbered ? String(i + 1) : r.num) + "\"><h2 class=\"qhead\" tabindex=\"-1\"><span>" + esc(headFn(r, i)) + "</span>" +
        "<span class=\"meta\">" + esc(meta.join(" · ")) + "</span><a href=\"" + hashOf("q", r.id, linkParams || {}) + "\">details</a>" + also + "</h2>";
      if (r.removed) {
        h += "<details class=\"rmbox\"><summary>Removed from the published paper for copyright reasons; only the markscheme remains. Show what is left of the page</summary>" +
          questionImage(r) + "</details>";
      } else h += sourceNotices(r) + questionImage(r);
      if (mode === "inline") h += "<div class=\"msinline\">" + msHtml(r, "h3", "Markscheme") + "</div>";
      h += "</li>";
    });
    h += "</ol>";
    if (mode === "end") {
      h += "<section class=\"msend\" aria-label=\"Markscheme\"><h2>Markscheme</h2>";
      rows.forEach(function (r, i) { h += "<div class=\"qblock\">" + msHtml(r, "h3", headFn(r, i)) + "</div>"; });
      h += "</section>";
    }
    return h;
  }
  function bindPrintAndMs() {
    var pr = $("#print");
    if (pr) pr.addEventListener("click", function () { window.print(); });
    $$("button[data-ms]").forEach(function (b) {
      b.addEventListener("click", function () { setParams({ ms: b.getAttribute("data-ms"), at: "" }, true); var nb = $("button[data-ms=\"" + b.getAttribute("data-ms") + "\"]"); if (nb) nb.focus(); });
    });
  }
  function stepBlock(dir) {
    var heads = $$(".qlist .qhead");
    if (!heads.length) return;
    var y = 4, cur = -1;
    heads.forEach(function (hd, i) { if (hd.getBoundingClientRect().top <= y + 2) cur = i; });
    var a = document.activeElement, ai = heads.indexOf(a);
    if (ai >= 0) cur = ai;
    var n = clamp(cur + dir, 0, heads.length - 1);
    if (dir > 0 && cur < 0) n = 0;
    heads[n].scrollIntoView({ block: "start" });
    heads[n].focus({ preventScroll: true });
  }

  // ---------------------------------------------------------------- Practice set
  function hashSeed(str) {
    var h = 1779033703 ^ str.length;
    for (var i = 0; i < str.length; i++) { h = Math.imul(h ^ str.charCodeAt(i), 3432918353); h = (h << 13) | (h >>> 19); }
    return function () { h = Math.imul(h ^ (h >>> 16), 2246822507); h = Math.imul(h ^ (h >>> 13), 3266489909); return (h ^= h >>> 16) >>> 0; };
  }
  function mulberry32(a) {
    return function () { a |= 0; a = (a + 0x6D2B79F5) | 0; var t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  }
  function newSeed() {
    var a = new Uint32Array(1);
    if (window.crypto && crypto.getRandomValues) crypto.getRandomValues(a); else a[0] = Math.floor(Math.random() * 4294967296);
    return a[0].toString(36).slice(0, 6).padStart(6, "0");
  }
  function practiceSet(pool, n, seed) {
    var arr = pool.slice().sort(function (a, b) { return a.idRank - b.idRank; });
    var rnd = mulberry32(hashSeed(String(seed))());
    var k = Math.min(n, arr.length);
    for (var i = 0; i < k; i++) {
      var j = i + Math.floor(rnd() * (arr.length - i));
      var t = arr[i]; arr[i] = arr[j]; arr[j] = t;
    }
    return arr.slice(0, k);
  }
  function viewPractice(rt) {
    var p = rt.params;
    var samePractice = main.getAttribute("data-view") === "practice";
    main.setAttribute("data-view", "practice");
    title("Practice set");
    if (!p.seed) { go(hashOf("practice", "", assign(p, { seed: newSeed() })), true); return; }
    var n = clamp(parseInt(p.n, 10) || 10, 1, 200);
    var scope = subjectsFor(validSubject(p.subject));
    if (parseSearch(p.q).length && !textReady(scope)) {
      main.innerHTML = "<h1>Practice set</h1><p class=\"status\">Loading question text&hellip;</p>";
      ensureText(scope).then(function () { if (CUR.view === "practice") route(); }, function (err) { main.innerHTML = "<p class=\"error\">" + esc(err.message) + "</p>"; });
      return;
    }
    var fp = pick(p, FILTER_KEYS);
    var res = questionQuery(fp, "practice");
    var set = practiceSet(res.rows, n, p.seed);
    var mode = p.ms === "inline" || p.ms === "off" ? p.ms : "end";
    var marks = 0;
    set.forEach(function (r) { marks += r.marks || 0; });
    var chips = chipsHtml(p, { fixed: true });
    var h = "<h1>Practice set</h1>" +
      "<p>" + plural(set.length, "question") + " drawn at random from " + plural(res.rows.length, "matching question") +
      (marks ? " &middot; " + plural(marks, "mark") : "") + " &middot; seed <code>" + esc(p.seed) + "</code></p>" +
      "<p class=\"note\">" + (res.hideDup ? "Each question appears once: " + plural(res.repeats, "repeated copy", "repeated copies") + " of questions set in more than one paper " + (res.repeats === 1 ? "is" : "are") + " left out." :
        "Repeated questions are included: the same question may appear twice (" + plural(res.repeats, "repeat") + " in the pool).") +
      (res.removedN && !res.showRemoved ? " " + plural(res.removedN, "question") + " removed from the published papers for copyright " + (res.removedN === 1 ? "is" : "are") + " left out." : "") + "</p>" +
      (chips ? "<div class=\"chips\">" + chips + "</div>" : "<p class=\"note no-print\">No filters: drawing from all questions.</p>") +
      "<form class=\"toolbar no-print\" id=\"pform\">" +
      "<label>Questions <input type=\"number\" id=\"pn\" min=\"1\" max=\"200\" value=\"" + n + "\"></label>" +
      "<label>Seed <input type=\"text\" id=\"pseed\" value=\"" + esc(p.seed) + "\" size=\"8\" spellcheck=\"false\"></label>" +
      "<label><input type=\"checkbox\" id=\"pdup\"" + (res.hideDup ? " checked" : "") + "> Skip repeated questions</label>" +
      "<button type=\"submit\">Apply</button><button type=\"button\" id=\"pnew\">New random set</button>" +
      "<span>Markscheme:</span><span class=\"seg\" role=\"group\" aria-label=\"Markscheme display\">" +
      [["off", "Hidden"], ["inline", "Under each question"], ["end", "At the end"]].map(function (o) {
        return "<button type=\"button\" data-pms=\"" + o[0] + "\" aria-pressed=\"" + (mode === o[0]) + "\">" + o[1] + "</button>";
      }).join("") + "</span>" +
      "<button type=\"button\" id=\"print\"" + (set.length ? "" : " disabled") + ">Print</button>" +
      "<a href=\"" + hashOf("questions", "", assign(fp, { dup: dupFor(res.hideDup, "questions") })) + "\">Change filters</a></form>";
    if (!set.length) h += "<p class=\"empty\">No questions match these filters.</p>";
    else {
      var desc = filterText(p);
      if (desc) h += "<p class=\"print-only\">Filters: " + esc(desc) + "</p>";
      h += questionBlocks(set, mode === "off" ? "" : mode, function (r, i) { return (i + 1) + ". " + examShort(r.ex) + " Q" + r.num; }, false, true);
    }
    if (samePractice) keepAnchor(function () { main.innerHTML = h; }); else main.innerHTML = h;
    upgradeTex(main);
    bindPrintAndMs();
    $("#pdup").addEventListener("change", function () { setParams({ dup: dupFor(this.checked, "practice") }, true); var c = $("#pdup"); if (c) c.focus(); });
    var needT = set.filter(function (r) { return r.S.textState === "none" && (!r.img || (!r.msImg && !r.mcq)); });
    if (needT.length) ensureText(needT.map(function (r) { return r.S; }).filter(function (S, i, a) { return a.indexOf(S) === i; })).then(function () { if (CUR.view === "practice") route(); }, function () {});
    $("#pform").addEventListener("submit", function (e) {
      e.preventDefault();
      setParams({ n: String(clamp(parseInt($("#pn").value, 10) || 10, 1, 200)), seed: $("#pseed").value.trim() || newSeed() }, true);
    });
    $("#pnew").addEventListener("click", function () { setParams({ seed: newSeed() }, true); });
    $$("button[data-pms]").forEach(function (b) {
      b.addEventListener("click", function () { var v = b.getAttribute("data-pms"); setParams({ ms: v === "end" ? "" : v }, true); var nb = $("button[data-pms=\"" + v + "\"]"); if (nb) nb.focus(); });
    });
  }

  // ---------------------------------------------------------------- Topics
  // Two ways to count a question with several topics, both shown and labelled:
  //   main topic: its first-listed topic (and the first listed subtopic of that topic); each question counts once
  //   any topic:  every topic and subtopic it covers; a question counts under each
  function viewTopics(rt) {
    var p = rt.params;
    title("Topics");
    var subj = validSubject(p.subject);
    if (!subj) {
      var first = DB.list.filter(function (S) { return S.rows.length; })[0] || DB.list[0];
      if (!first) { main.innerHTML = "<h1>Topics</h1><p class=\"empty\">No data.</p>"; return; }
      go(hashOf("topics", "", assign(p, { subject: first.id })), true);
      return;
    }
    var S = DB.byId[subj];
    var created = shell("topics",
      "<div class=\"layout\"><aside class=\"side no-print\" aria-label=\"Filters\"><details class=\"fbox\" id=\"fbox\" open><summary>Filters</summary>" +
      "<form class=\"filters\" id=\"filters\" autocomplete=\"off\"></form></details></aside>" +
      "<section class=\"content\" id=\"tcontent\"></section></div>");
    var form = $("#filters"), content = $("#tcontent");
    if (created) {
      if (window.matchMedia("(max-width: 860px)").matches) $("#fbox").open = false;
      bindFilterForm(form);
      content.addEventListener("change", function (e) {
        if (e.target.id === "trows") setParams({ rows: e.target.value === "year" ? "" : e.target.value });
        if (e.target.id === "tcols") setParams({ cols: e.target.value });
        if (e.target.id === "tcount") setParams({ tcount: e.target.value === "primary" ? "primary" : "" });
        var f = e.target.id && document.getElementById(e.target.id);
        if (f) f.focus();
      });
      bindChips(content);
      content.addEventListener("click", function (e) {
        var j = e.target.closest("a[data-jump]");
        if (!j) return;
        e.preventDefault();
        var el = document.getElementById(j.getAttribute("data-jump"));
        if (el) { el.setAttribute("tabindex", "-1"); el.scrollIntoView(); el.focus({ preventScroll: true }); }
      });
    }
    var tp = assign(p, { topic: "", sub: "", tmode: "", sort: "", group: "", page: "", per: "" });
    if (parseSearch(p.q).length && !textReady([S])) {
      content.innerHTML = "<p class=\"status\">Loading question text&hellip;</p>";
      ensureText([S]).then(function () { if (CUR.view === "topics") route(); }, function () {});
      return;
    }
    var res = questionQuery(tp, "topics");
    // sidebar (no topic filter here)
    var scopeKey = "q:" + subj;
    var h = subjectSelect(p, false, function (X) { return visibleCount(X, p); });
    h += repeatFieldset(res, "topics");
    h += rangeFieldset("year", "Year", p, yearsOf(S.exams));
    QFACETS.forEach(function (f) {
      if (f.topic) return;
      h += facetFieldset(f, facetValues(scopeKey, S.rows, f), res.counts[f.p], res.sel[f.p] ? res.sel[f.p].set : null);
    });
    h += rangeFieldset("marks", "Marks", p, null);
    h += "<fieldset class=\"fg\"><legend>Text</legend><label class=\"vh\" for=\"f-q\">Search text</label><input type=\"search\" id=\"f-q\" class=\"full\" data-p=\"q\" value=\"" + esc(p.q || "") + "\" placeholder=\"Search text\"></fieldset>";
    h += "<div class=\"actions\"><button type=\"button\" data-clear=\"1\">Clear all filters</button></div>";
    preserveFocus(form.closest(".side"), function () { form.innerHTML = h; });

    var rows = res.rows, anyC = new Map(), mainC = new Map(), un = 0, multiN = 0;
    var inc = function (m, c) { m.set(c, (m.get(c) || 0) + 1); };
    rows.forEach(function (r) {
      if (!r.tp.length) { un++; return; }
      if (r.tp.length > 1) multiN++;
      r.tp.forEach(function (c) { inc(anyC, c); });
      r.su.forEach(function (c) { inc(anyC, c); });
      r.pcodes.forEach(function (c) { inc(mainC, c); });
    });
    var classified = rows.length - un;
    // links open the question list with the same filters and the same treatment of repeats
    var base = assign(pick(tp, FILTER_KEYS), { dup: dupFor(res.hideDup, "questions") });
    var qlink = function (extra, n, tip) {
      return n ? "<a href=\"" + hashOf("questions", "", assign(base, extra)) + "\"" + (tip ? " title=\"" + esc(tip) + "\"" : "") + ">" + fmt(n) + "</a>" : "<span class=\"zero\">0</span>";
    };
    var pct = function (n) { return rows.length ? (100 * n / rows.length).toFixed(1) : "0.0"; };
    var out = "<h1>Topics &ndash; " + esc(S.name) + "</h1>";
    var chips = chipsHtml(tp, { noSubject: true, view: "topics" });
    if (chips) out += "<div class=\"chips\">" + chips + "</div>";
    out += "<p>" + plural(rows.length, "question") + " match the filters (" + fmt(classified) + " classified, " + fmt(multiN) + " of them with more than one topic). " +
      (res.hideDup ? "Repeated questions are counted once" + (res.repeats ? " (" + plural(res.repeats, "repeated copy", "repeated copies") + " left out)" : "") + "."
        : "Repeated questions are counted every time they were set" + (res.repeats ? " (" + plural(res.repeats, "repeat") + " included)" : "") + ".") + "</p>" +
      "<dl class=\"defs\"><dt>Main topic</dt><dd>questions whose main (first-listed) topic is this one; for a subtopic, the first listed subtopic of the main topic. " +
      "Each classified question is counted exactly once, so the topic rows add up to " + fmt(classified) + ".</dd>" +
      "<dt>Any topic</dt><dd>questions that cover the topic at all, as main or secondary topic. A question with several topics is counted under each of them, so these add up to more.</dd></dl>" +
      "<p class=\"no-print\">Jump to: <a href=\"#h-tree\" data-jump=\"h-tree\">topic tree</a> &middot; <a href=\"#h-matrix\" data-jump=\"h-matrix\">year and topic table</a></p>";
    out += "<h2 id=\"h-tree\">Topic tree</h2><div class=\"tablewrap\"><table class=\"grid tree-table\" aria-labelledby=\"h-tree\"><thead><tr>" +
      "<th scope=\"col\">Code</th><th scope=\"col\">Topic</th>" +
      "<th scope=\"col\" class=\"num\" title=\"Questions with this as their main topic or subtopic\">Main topic</th><th scope=\"col\" class=\"num\">%</th>" +
      "<th scope=\"col\" class=\"num\" title=\"Questions that cover this topic, as main or secondary topic\">Any topic</th><th scope=\"col\" class=\"num\">%</th></tr></thead><tbody>";
    S.tax.forEach(function (T) {
      var nm = mainC.get(T.code) || 0, na = anyC.get(T.code) || 0;
      out += "<tr class=\"lvl0\"><td class=\"mono\">" + esc(T.code) + "</td><td class=\"wrap\">" + esc(T.name) + "</td>" +
        "<td class=\"num\">" + qlink({ topic: T.code, tmode: "primary" }, nm, "Main topic " + T.code) + "</td><td class=\"num\">" + pct(nm) + "</td>" +
        "<td class=\"num\">" + qlink({ topic: T.code }, na, "Any topic " + T.code) + "</td><td class=\"num\">" + pct(na) + "</td></tr>";
      T.subs.forEach(function (U) {
        var um = mainC.get(U.code) || 0, ua = anyC.get(U.code) || 0;
        out += "<tr><td class=\"mono ind\">" + esc(U.code) + "</td><td class=\"wrap\">" + esc(U.name) + "</td>" +
          "<td class=\"num\">" + qlink({ sub: U.code, tmode: "primary" }, um, "Main subtopic " + U.code) + "</td><td class=\"num\">" + pct(um) + "</td>" +
          "<td class=\"num\">" + qlink({ sub: U.code }, ua, "Any subtopic " + U.code) + "</td><td class=\"num\">" + pct(ua) + "</td></tr>";
      });
    });
    out += "<tr class=\"lvl0\"><td></td><td>Unclassified</td><td class=\"num\">" + qlink({ topic: "none" }, un) + "</td><td class=\"num\">" + pct(un) + "</td>" +
      "<td class=\"num\">" + qlink({ topic: "none" }, un) + "</td><td class=\"num\">" + pct(un) + "</td></tr></tbody>" +
      "<tfoot><tr><th scope=\"row\" colspan=\"2\">All matching questions</th><td class=\"num\">" + fmt(rows.length) + "</td><td class=\"num\">100.0</td><td></td><td></td></tr></tfoot></table></div>";

    // matrix
    var byRows = p.rows === "session" ? "session" : "year";
    var cmode = p.tcount === "primary" ? "primary" : "any";
    var colT = p.cols && S.codes.get(p.cols) && S.codes.get(p.cols).subs ? S.codes.get(p.cols) : null;
    var colsL = colT ? colT.subs : S.tax;
    out += "<h2 id=\"h-matrix\">Questions per " + (byRows === "year" ? "year" : "exam session") + " and " + (colT ? "subtopic of " + esc(colT.code + " " + colT.name) : "topic") +
      " <span class=\"sub\">(" + (cmode === "primary" ? "main topic only" : "any topic") + ")</span></h2>" +
      "<div class=\"toolbar no-print\"><label>Rows <select id=\"trows\"><option value=\"year\"" + (byRows === "year" ? " selected" : "") + ">Year</option><option value=\"session\"" + (byRows === "session" ? " selected" : "") + ">Exam session</option></select></label>" +
      "<label>Columns <select id=\"tcols\"><option value=\"\">Topics</option>" + S.tax.filter(function (T) { return T.subs.length; }).map(function (T) {
        return "<option value=\"" + esc(T.code) + "\"" + (colT === T ? " selected" : "") + ">Subtopics of " + esc(T.code + " " + T.name) + "</option>";
      }).join("") + "</select></label>" +
      "<label>Count <select id=\"tcount\"><option value=\"any\"" + (cmode === "any" ? " selected" : "") + ">Any topic a question covers</option>" +
      "<option value=\"primary\"" + (cmode === "primary" ? " selected" : "") + ">Main topic only</option></select></label></div>" +
      "<p class=\"note\">" + (cmode === "primary" ? "Each question is counted once, under its main " + (colT ? "subtopic" : "topic") + "; a row adds up to its total minus unclassified questions" + (colT ? " and questions whose main topic is not " + esc(colT.code) : "") + "."
        : "A question with several " + (colT ? "subtopics" : "topics") + " is counted in each of their columns, so a row can add up to more than its total.") + "</p>";
    var keyOf = byRows === "year" ? function (r) { return r.ex.year * 2; } : function (r) { return r.ex.year * 2 + r.ex.sessIdx; };
    var mat = new Map(), rowTot = new Map(), colTot = new Map(), maxv = 0;
    rows.forEach(function (r) {
      var k = keyOf(r), set = cmode === "primary" ? r.pset : r.tset;
      rowTot.set(k, (rowTot.get(k) || 0) + 1);
      for (var ci = 0; ci < colsL.length; ci++) {
        var c = colsL[ci];
        if (!set.has(c.code)) continue;
        var key = k + "|" + c.code, v = (mat.get(key) || 0) + 1;
        mat.set(key, v); if (v > maxv) maxv = v;
        colTot.set(c.code, (colTot.get(c.code) || 0) + 1);
      }
    });
    var keys = Array.from(rowTot.keys()).sort(function (a, b) { return b - a; });
    var param = colT ? "sub" : "topic";
    var modeExtra = cmode === "primary" ? { tmode: "primary" } : {};
    out += "<div class=\"tablewrap\"><table class=\"grid matrix\" aria-labelledby=\"h-matrix\"><thead><tr><th scope=\"col\" class=\"rowh\">" + (byRows === "year" ? "Year" : "Session") + "</th>" +
      colsL.map(function (c) { return "<th scope=\"col\"><abbr title=\"" + esc(c.code + " " + c.name) + "\">" + esc(c.code) + "</abbr></th>"; }).join("") +
      "<th scope=\"col\">Questions</th></tr></thead><tbody>";
    keys.forEach(function (k) {
      var y = Math.floor(k / 2), sess = k % 2 ? "November" : "May";
      var rowExtra = byRows === "year" ? { year: String(y) } : { year: String(y), session: sess };
      out += "<tr><th scope=\"row\" class=\"rowh\">" + (byRows === "year" ? y : esc(sess + " " + y)) + "</th>";
      colsL.forEach(function (c) {
        var v = mat.get(k + "|" + c.code) || 0;
        var ex = assign(assign(rowExtra, modeExtra), {}); ex[param] = c.code;
        out += v ? "<td class=\"c\" style=\"--v:" + (v / maxv).toFixed(3) + "\"><a href=\"" + hashOf("questions", "", assign(base, ex)) + "\" title=\"" + esc((byRows === "year" ? y : sess + " " + y) + ", " + c.code + " " + c.name + ": " + v) + "\">" + v + "</a></td>" : "<td class=\"z\">&middot;</td>";
      });
      out += "<td>" + qlink(rowExtra, rowTot.get(k)) + "</td></tr>";
    });
    if (!keys.length) out += "<tr><td colspan=\"" + (colsL.length + 2) + "\" class=\"empty\">No questions match these filters.</td></tr>";
    out += "</tbody><tfoot><tr><th scope=\"row\" class=\"rowh\">Total</th>" + colsL.map(function (c) { var ex = assign(modeExtra, {}); ex[param] = c.code; return "<td>" + qlink(ex, colTot.get(c.code) || 0) + "</td>"; }).join("") +
      "<td>" + fmt(rows.length) + "</td></tr></tfoot></table></div>";
    content.innerHTML = out;
  }

  // ---------------------------------------------------------------- Help
  function viewHelp() {
    main.setAttribute("data-view", "help");
    title("Help");
    var cov = "<table class=\"grid\"><thead><tr><th scope=\"col\">Subject</th><th scope=\"col\">Syllabuses</th><th scope=\"col\" class=\"num\">Papers catalogued</th><th scope=\"col\" class=\"num\">Extracted</th><th scope=\"col\" class=\"num\">Questions</th><th scope=\"col\" class=\"num\">Classified</th><th scope=\"col\" class=\"num\">With markscheme</th><th scope=\"col\" class=\"num\">Transcribed</th><th scope=\"col\" class=\"num\" title=\"Questions that are copies of a question in another paper\">Repeats</th><th scope=\"col\">Years</th></tr></thead><tbody>";
    var tot = [0, 0, 0, 0, 0, 0, 0], remTot = 0;
    DB.list.forEach(function (S) {
      var ext = S.exams.filter(function (e) { return e.status !== "unprocessed"; }).length;
      var cls = S.rows.filter(function (r) { return r.tp.length; }).length;
      var ms = S.rows.filter(function (r) { return r.ans !== "missing"; }).length;
      var ys = yearsOf(S.exams);
      var tr = S.rows.filter(function (r) { return r.clean; }).length;
      var rep = S.rows.length - dedupeRows(S.rows).length;
      var nq = visibleCount(S, {});
      remTot += S.rows.length - nq;
      tot[0] += S.exams.length; tot[1] += ext; tot[2] += nq; tot[3] += cls; tot[4] += ms; tot[5] += tr; tot[6] += rep;
      cov += "<tr><td>" + esc(S.name) + "</td><td class=\"wrap\">" + S.syllabuses.map(function (s) { return esc(s.name); }).join("; ") + "</td><td class=\"num\"><a href=\"" + hashOf("papers", "", { subject: S.id }) + "\">" + fmt(S.exams.length) + "</a></td><td class=\"num\">" + fmt(ext) +
        "</td><td class=\"num\"><a href=\"" + hashOf("questions", "", { subject: S.id }) + "\">" + fmt(nq) + "</a></td><td class=\"num\">" + fmt(cls) + "</td><td class=\"num\">" + fmt(ms) + "</td><td class=\"num\">" + fmt(tr) + "</td><td class=\"num\"><a href=\"" + hashOf("questions", "", { subject: S.id, flag: "repeat" }) + "\">" + fmt(rep) + "</a></td><td>" + (ys.length ? ys[0] + "&ndash;" + ys[ys.length - 1] : "") + "</td></tr>";
    });
    cov += "</tbody><tfoot><tr><th scope=\"row\">Total</th><td></td>" + tot.map(function (v) { return "<td class=\"num\">" + fmt(v) + "</td>"; }).join("") + "<td></td></tr></tfoot></table>";
    var keys = [["/", "Focus the search box"], ["j", "Next question (list: next row; question page: next question; paper: next question)"], ["k", "Previous question"],
      ["Enter", "Open the focused question"], ["m", "Show or hide the markscheme"], ["Esc", "Leave a text field"], ["?", "This page"]];
    var params = [["subject", "math, physics, economics"], ["syllabus", "syllabus ids, comma separated"], ["year", "2015, 2015-2020, 2015- or -2010"],
      ["session", "May, November"], ["tz", "TZ1, TZ2, TZ3, none"], ["paper", "1, 1A, 1B, 2, 3"], ["option", "legacy paper 3 option, e.g. calculus; none"],
      ["section", "A, B, none"], ["qtype", "mcq, short, long, essay, data"], ["marks", "range, e.g. 4-8"], ["topic / sub", "taxonomy codes (needs subject); topic=none for unclassified"],
      ["tmode", "all = question must have every selected topic; primary = the selected topic is the question's main topic (default any)"], ["ans", "ok, suspect, missing"],
      ["flag", ISSUES.map(function (x) { return x[0]; }).join(", ") + ", none"],
      ["dup", "hide or show repeated questions (default: shown in lists, hidden in practice sets and topic counts)"], ["removed", "show = include questions removed for copyright"],
      ["q", "text search; words are combined with AND, \"quoted phrase\", -word excludes"], ["in", "q = question text only, ms = markscheme text only"],
      ["exam", "exam ids"], ["sort", "column:asc|desc, comma separated, e.g. year:desc,marks:asc"], ["group", "subject, year, exam, paper, topic"],
      ["per / page", "rows per page, page number"], ["n / seed / ms", "practice set: number of questions, random seed, markscheme placement (end, inline, off)"],
      ["rows / cols / tcount", "topics table: rows by year or session, columns topics or subtopics of one topic, count any topic or main topic only (primary)"]];
    var flagRows = ISSUES.map(function (x) {
      var desc = x[2] ? x[2].map(function (f) { return FLAG_INFO[f] ? FLAG_INFO[f].desc : f; }).join(" ") :
        x[0] === "repeat" ? "The same question was also set in another paper (for example both time zones of one session)." :
        x[0] === "auto-text" ? "The question text has not been transcribed by hand; it was extracted automatically and may contain errors." :
        "A reviewer added a note, shown on the question page.";
      return "<tr><th scope=\"row\">" + esc(x[1]) + "</th><td>" + esc(desc) + "</td></tr>";
    }).join("");
    main.innerHTML = "<div class=\"help\"><h1>Help</h1>" +
      "<p>A catalogue of past examination questions. Every question is cut from the original paper and kept as an image together with its markscheme, a transcription of its text, and topic codes from one taxonomy per subject that is applied to all years, so old and new syllabus papers can be filtered together.</p>" +
      "<h2>Coverage</h2><div class=\"tablewrap\">" + cov + "</div>" +
      "<p class=\"note\">“Extracted” papers have been cut into questions. Papers that are catalogued but not yet extracted are listed under <a href=\"#/papers?status=unprocessed\">Papers</a>." +
      (remTot ? " Questions do not include the " + plural(remTot, "question") + " removed from the published papers for copyright reasons." : "") +
      " Repeats are copies of a question that was also set in another paper; they are included in the question counts.</p>" +
      "<h2>Using the lists</h2><ul><li>Click a column heading to sort; shift-click to add it as a further sort key. Click again to reverse.</li>" +
      "<li>Filters in the left column combine with AND; ticked values within one group combine with OR. Topic filters can be switched to match all ticked topics.</li>" +
      "<li>The numbers next to each filter value show how many results you would get with that value, given the other filters.</li>" +
      "<li>Every view is described by its address, so a filtered list, a question or a practice set can be bookmarked or shared.</li>" +
      "<li>Practice sets draw questions at random from the current filters. The seed in the address makes the same set reappear.</li></ul>" +
      "<h2>Keyboard</h2><table class=\"kv\"><tbody>" + keys.map(function (k) { return "<tr><th scope=\"row\"><kbd>" + esc(k[0]) + "</kbd></th><td>" + esc(k[1]) + "</td></tr>"; }).join("") + "</tbody></table>" +
      "<h2>Transcriptions</h2><p>Most questions have a transcription typed from the paper, shown on the question page next to the page image (use the switch above the question to show one or both). " +
      "Mathematics is written in LaTeX and displayed with KaTeX; figures are described in square brackets. “Copy question text” copies the transcription with its LaTeX source. Where no transcription exists, the text extracted automatically from the PDF is used for searching.</p>" +
      "<h2>Repeated questions</h2><p>Some papers were set in two time zones with identical questions (for example November 2023), and a few questions were reused verbatim. " +
      "These are detected by comparing the question text and are linked on the question page under “Also appeared as”. Lists show every copy by default; tick “Hide repeated questions” to keep one copy of each. " +
      "Practice sets and the topic counts hide repeats by default so that a question is not drawn or counted twice; both pages say so and offer the same switch.</p>" +
      "<h2>Questions removed for copyright</h2><p>Some published papers omit text extracts, figures or whole questions for copyright reasons. Questions that are missing entirely (only the markscheme survives) are hidden everywhere unless “Include questions removed for copyright” is ticked; in a paper they are collapsed. Questions with part of their content missing are shown with a notice.</p>" +
      "<h2>Main topic and any topic</h2><p>A question can have several topics; the first is its main topic. The topic tree shows both counts: <b>main topic</b> counts every question once, under its main topic; <b>any topic</b> counts a question under every topic it covers. " +
      "The topic filter can match any ticked topic, all of them, or the main topic only.</p>" +
      "<h2>Flags</h2><table class=\"kv\"><tbody>" + flagRows + "</tbody></table>" +
      "<h2>Markscheme status</h2><table class=\"kv\"><tbody><tr><th scope=\"row\">Available</th><td>A markscheme was matched to the question.</td></tr><tr><th scope=\"row\">Suspect</th><td>A markscheme was found but the match may be wrong or incomplete.</td></tr><tr><th scope=\"row\">Missing</th><td>No markscheme for this question.</td></tr></tbody></table>" +
      "<h2>Address parameters</h2><table class=\"kv\"><tbody>" + params.map(function (k) { return "<tr><th scope=\"row\"><code>" + esc(k[0]) + "</code></th><td>" + esc(k[1]) + "</td></tr>"; }).join("") + "</tbody></table>" +
      "<p class=\"note\">Data build <code>" + esc(DB.index && DB.index.build || BUILD) + "</code>.</p></div>";
  }

  // ---------------------------------------------------------------- keyboard
  function isTyping(t) {
    if (!t || !t.closest) return false;
    if (t.closest("textarea, select, [contenteditable=\"true\"]")) return true;
    var inp = t.closest("input");
    return !!inp && !/^(checkbox|radio|button|submit|reset)$/.test(inp.type);
  }
  function stepRow(dir) {
    var links = $$("#results a.qid");
    if (!links.length) return;
    var i = links.indexOf(document.activeElement);
    if (i < 0) { (dir > 0 ? links[0] : links[links.length - 1]).focus(); return; }
    var n = i + dir;
    if (n >= 0 && n < links.length) { links[n].focus(); return; }
    var pg = $(".pager a[rel=\"" + (dir > 0 ? "next" : "prev") + "\"]");
    if (pg) { pendingFocus = dir > 0 ? "first" : "last"; go(pg.getAttribute("href")); }
  }
  function onKey(e) {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
    var t = e.target;
    if (e.key === "Escape") {
      var disp = $("#display");
      if (disp && disp.open) { disp.open = false; $("summary", disp).focus(); return; }
      if (isTyping(t)) { t.blur(); return; }
      return;
    }
    if (isTyping(t)) return;
    var v = CUR.view;
    if (e.key === "/") {
      var s = $("#qsearch") || $("#psearch") || $("#f-q");
      e.preventDefault();
      if (s) { s.focus(); s.select(); }
      else { pendingFocus = "search"; go(lastQuestionsHash); }
    } else if (e.key === "j" || e.key === "k") {
      var dir = e.key === "j" ? 1 : -1;
      if (v === "q") { var a = $(dir > 0 ? "#next" : "#prev"); if (a) go(a.getAttribute("href")); }
      else if (v === "questions" || v === "papers") stepRow(dir);
      else if (v === "paper" || v === "practice") stepBlock(dir);
      else return;
      e.preventDefault();
    } else if (e.key === "m") {
      if (v === "q") toggleMs();
      else if (v === "paper") setParams({ ms: msModeOf(CUR.params) ? "" : lastMsMode, at: "" }, true);
      else if (v === "practice") setParams({ ms: CUR.params.ms === "off" ? "" : "off" }, true);
      else return;
      e.preventDefault();
    } else if (e.key === "?") {
      go("#/help");
      e.preventDefault();
    }
  }

  // ---------------------------------------------------------------- start
  function initChrome() {
    applyPrefs();
    $$("input[name=theme]").forEach(function (r) {
      r.checked = r.value === prefs.theme;
      r.addEventListener("change", function () { if (r.checked) { prefs.theme = r.value; applyPrefs(); savePrefs(); } });
    });
    var inv = $("#pref-invert");
    inv.checked = prefs.invert;
    inv.addEventListener("change", function () { prefs.invert = inv.checked; applyPrefs(); savePrefs(); });
    document.addEventListener("click", function (e) {
      var d = $("#display");
      if (d && d.open && !d.contains(e.target)) d.open = false;
    });
    $("#skip").addEventListener("click", function (e) { e.preventDefault(); main.focus(); });
    document.addEventListener("keydown", onKey);
  }

  function start() {
    main = $("#main");
    initChrome();
    load().then(function () {
      window.addEventListener("hashchange", onHistory);
      window.addEventListener("popstate", onHistory);
      if (!location.hash || location.hash === "#" || location.hash === "#/") history.replaceState(null, "", "#/questions");
      route();
    }, function (err) {
      main.innerHTML = "<h1>Could not load the database</h1><p class=\"error\">" + esc(err.message) + "</p>" +
        "<p>The site must be served over HTTP (for example <code>python3 -m http.server</code> in the build directory); it cannot be opened as a local file.</p>";
      if (window.console) console.error(err);
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
