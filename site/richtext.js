/* Renders question transcriptions (text_clean) as HTML.
 *
 * Input conventions (see pipeline/labels.py): one line per printed line or option, maths in $...$ or $$...$$,
 * \$ for a literal dollar sign, [Diagram: ...] style descriptions of figures, **bold** for printed emphasis,
 * and simple "a | b | c" rows for printed tables.
 *
 * QText.html(text, katex) -> HTML string. With katex == null (not loaded, or failed to load) maths is shown as
 * its plain LaTeX source, so the text is always readable. Each formula KaTeX cannot parse falls back the same way.
 * Works in the browser (window.QText) and in node (module.exports) for tests.
 */
(function (root) {
  "use strict";

  var ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" };
  function esc(v) { return v == null ? "" : String(v).replace(/[&<>"']/g, function (c) { return ESC[c]; }); }

  // Split into text / inline maths / display maths. Inline $...$ uses the usual rules for telling maths from
  // prices: the opening $ is followed by a non-space (and is not a currency sign between a letter and a digit,
  // "US$21"), the closing $ is not followed by a digit, and inline maths never spans a line. A $ without a valid
  // partner stays literal text ("US$21 715").
  function tokenize(s) {
    var out = [], buf = "", i = 0, n = s.length;
    function flush() { if (buf) { out.push({ t: "text", v: buf }); buf = ""; } }
    while (i < n) {
      var c = s.charAt(i);
      if (c === "\\" && s.charAt(i + 1) === "$") { buf += "$"; i += 2; continue; }
      if (c !== "$") { buf += c; i++; continue; }
      if (s.charAt(i + 1) === "$") {
        var j = s.indexOf("$$", i + 2);
        if (j > i + 2) { flush(); out.push({ t: "dmath", v: s.slice(i + 2, j) }); i = j + 2; continue; }
        buf += "$$"; i += 2; continue;
      }
      var end = findClose(s, i);
      if (end < 0) { buf += "$"; i++; continue; }
      flush();
      out.push({ t: "math", v: s.slice(i + 1, end) });
      i = end + 1;
    }
    flush();
    return out;
  }
  function findClose(s, i) {
    var first = s.charAt(i + 1);
    if (!first || /\s/.test(first)) return -1;
    if (/[0-9]/.test(first) && /[A-Za-z]/.test(s.charAt(i - 1) || "")) return -1;   // US$21, NZ$5
    for (var k = i + 1; k < s.length; k++) {
      var c = s.charAt(k);
      if (c === "\n") return -1;
      if (c === "\\") { k++; continue; }
      if (c !== "$") continue;
      if (s.charAt(k + 1) === "$") return -1;
      if (/[0-9]/.test(s.charAt(k + 1) || "") || k === i + 1) continue;
      return k;
    }
    return -1;
  }

  // Split the token stream into lines (display maths is a line of its own).
  function lines(tokens) {
    var out = [[]];
    tokens.forEach(function (tk) {
      if (tk.t === "dmath") { out.push([tk]); out.push([]); return; }
      if (tk.t === "math") { out[out.length - 1].push(tk); return; }
      var parts = tk.v.split("\n");
      parts.forEach(function (p, k) {
        if (k > 0) out.push([]);
        if (p) out[out.length - 1].push({ t: "text", v: p });
      });
    });
    return out;
  }

  // Inline fractions are set in display style, as in the printed papers (KaTeX's text style makes them tiny).
  var BIG_INLINE = /\\(?:frac|binom)(?![A-Za-z])/;
  function mathHtml(src, display, katex, stats) {
    if (katex) {
      try {
        var tex = !display && BIG_INLINE.test(src) && !/^\s*\\(?:display|text|script)style/.test(src) ? "\\displaystyle " + src : src;
        var h = katex.renderToString(tex, { displayMode: display, throwOnError: true, strict: "ignore", trust: false, output: "htmlAndMathml" });
        if (stats) stats.ok++;
        return display ? "<div class=\"dmath\">" + h + "</div>" : h;
      } catch (e) {
        if (stats) { stats.failed++; stats.errors.push(src); }
      }
    }
    var d = display ? "$$" : "$";
    return "<span class=\"tex\">" + esc(d + src + d) + "</span>";
  }

  var DESC = /^\[(?!Maximum mark)([A-Za-z][^\]]{6,})\]/;
  // Plain-text pieces: **bold**, [figure descriptions], trailing [n] / [n marks] mark allocations.
  function textHtml(v) {
    var out = "", rest = v;
    while (rest) {
      var b = rest.indexOf("[");
      if (b < 0) { out += inline(rest); break; }
      out += inline(rest.slice(0, b));
      rest = rest.slice(b);
      var close = matchBracket(rest);
      var seg = close > 0 ? rest.slice(0, close + 1) : null;
      if (seg && DESC.test(seg)) { out += "<span class=\"desc\">" + inline(seg.slice(1, -1)) + "</span>"; rest = rest.slice(close + 1); }
      else if (seg && /^\[\d+(?: marks?)?\]$/.test(seg)) { out += "<span class=\"mk\">" + esc(seg) + "</span>"; rest = rest.slice(close + 1); }
      else { out += "["; rest = rest.slice(1); }
    }
    return out;
  }
  function matchBracket(s) {
    var depth = 0;
    for (var i = 0; i < s.length; i++) {
      if (s.charAt(i) === "[") depth++;
      else if (s.charAt(i) === "]") { depth--; if (!depth) return i; }
    }
    return -1;
  }
  function inline(v) {
    return esc(v).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  }

  // A line is rendered segment by segment; [descriptions] may contain maths, so brackets are matched across
  // segments by first rendering text and maths in order and only then detecting description spans on the text.
  function lineHtml(segs, katex, stats) {
    // join text segments with placeholders for maths so bracket detection sees the whole line
    var maths = [], joined = "";
    segs.forEach(function (sg) {
      if (sg.t === "text") joined += sg.v.replace(/\u0000/g, "");
      else { joined += "\u0000" + maths.length + "\u0000"; maths.push(sg); }
    });
    var h = textHtml(joined);
    return h.replace(/\u0000(\d+)\u0000/g, function (m, k) { return mathHtml(maths[+k].v, false, katex, stats); });
  }

  function textOf(segs) { return segs.map(function (sg) { return sg.t === "text" ? sg.v : ""; }).join(""); }
  function isRow(segs) {
    if (!segs.length || segs[0].t === "dmath") return false;
    var t = textOf(segs).replace(/\[[^\]]*\]/g, "");
    return t.indexOf("|") >= 0;
  }
  function isSepRow(segs) { return segs.every(function (sg) { return sg.t === "text" && /^[\s|:\-]*$/.test(sg.v); }); }
  function splitCells(segs) {
    var cells = [[]];
    var depth = 0;
    segs.forEach(function (sg) {
      if (sg.t !== "text") { cells[cells.length - 1].push(sg); return; }
      var cur = "";
      for (var i = 0; i < sg.v.length; i++) {
        var c = sg.v.charAt(i);
        if (c === "[") depth++;
        else if (c === "]" && depth) depth--;
        if (c === "|" && !depth) {
          if (cur) cells[cells.length - 1].push({ t: "text", v: cur });
          cur = ""; cells.push([]);
        } else cur += c;
      }
      if (cur) cells[cells.length - 1].push({ t: "text", v: cur });
    });
    var blank = function (c) { return !c.length || (c.length === 1 && c[0].t === "text" && !c[0].v.trim()); };
    if (cells.length > 1 && blank(cells[0]) && textOf(segs).replace(/^\s+/, "").charAt(0) === "|") cells.shift();
    if (cells.length > 1 && blank(cells[cells.length - 1]) && /\|\s*$/.test(textOf(segs))) cells.pop();
    return cells.map(function (c) {
      if (c.length && c[0].t === "text") c[0] = { t: "text", v: c[0].v.replace(/^\s+/, "") };
      var l = c.length - 1;
      if (l >= 0 && c[l].t === "text") c[l] = { t: "text", v: c[l].v.replace(/\s+$/, "") };
      return c;
    });
  }

  var ROMAN = /^\((?:i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii)\)\s/;
  var LETTER = /^\(([a-z])\)\s/;
  var OPTION = /^[A-D]\.\s/;

  function html(text, katex, stats) {
    if (text == null || text === "") return "";
    var ls = lines(tokenize(String(text).replace(/\r\n?/g, "\n")));
    var out = "", i = 0, lastLetter = null;
    while (i < ls.length) {
      var segs = ls[i];
      if (isRow(segs) && i + 1 < ls.length && isRow(ls[i + 1])) {
        var rows = [];
        while (i < ls.length && isRow(ls[i])) { if (!isSepRow(ls[i])) rows.push(splitCells(ls[i])); i++; }
        var w = 0;
        rows.forEach(function (r) { if (r.length > w) w = r.length; });
        out += "<div class=\"ttab\"><table>" + rows.map(function (r) {
          var cells = r.slice();
          while (cells.length < w) cells.push([]);
          return "<tr>" + cells.map(function (c) { return "<td>" + lineHtml(c, katex, stats) + "</td>"; }).join("") + "</tr>";
        }).join("") + "</table></div>";
        continue;
      }
      i++;
      if (!segs.length) continue;
      if (segs.length === 1 && segs[0].t === "dmath") { out += mathHtml(segs[0].v, true, katex, stats); continue; }
      var lead = segs[0].t === "text" ? segs[0].v.replace(/^\s+/, "") : "";
      var cls = "ln";
      var lm = LETTER.exec(lead);
      if (ROMAN.test(lead) && !(lm && lm[1] === "i" && lastLetter === "h") && !(lm && lm[1] === "v" && lastLetter === "u")) cls += " l2";
      else if (lm) { cls += " l1"; lastLetter = lm[1]; }
      else if (OPTION.test(lead)) cls += " opt";
      var body = lineHtml(segs, katex, stats);
      if (!body.replace(/<[^>]*>/g, "").trim() && body.indexOf("katex") < 0) continue;
      out += "<p class=\"" + cls + "\">" + body + "</p>";
    }
    return out;
  }

  // Inline-only rendering for short notes (no line structure beyond line breaks).
  function inlineHtml(text, katex, stats) {
    if (text == null || text === "") return "";
    return lines(tokenize(String(text))).map(function (segs) { return lineHtml(segs, katex, stats); }).join("<br>");
  }

  var api = { html: html, inlineHtml: inlineHtml, tokenize: tokenize, hasMath: function (t) { return tokenize(String(t || "")).some(function (x) { return x.t !== "text"; }); } };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.QText = api;
})(typeof window !== "undefined" ? window : this);
