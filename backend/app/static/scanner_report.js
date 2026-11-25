/* Charting Lab theme for the SwingScanner report (added by app/api/scanner_report.py). Uses the app's day / night
   choice (localStorage "theme", shared because the report is served from the app's own address), recolours the
   report's lightweight-charts, and tells the report's scripts where this route lives. */
(function () {
  var p = location.pathname, k = p.indexOf("/scanner/report/");
  window.__SCAN_BASE = k >= 0 ? p.slice(0, k + "/scanner/report/".length) : "/";

  var read = function () {
    try { var t = JSON.parse(localStorage.getItem("theme") || '"light"'); return t === "dark" ? "dark" : "light"; }
    catch (e) { return "light"; }
  };
  var theme = read();
  document.documentElement.dataset.theme = theme;

  var PAL = {
    light: { bg: "#ffffff", text: "#434651", grid: "#f0f3fa", border: "#e0e3eb", cross: "#9598a1" },
    dark: { bg: "#12161e", text: "#a7adbb", grid: "#1a1f29", border: "#262b36", cross: "#5d6575" },
  };
  var charts = [];
  var opts = function (t) {
    var c = PAL[t];
    return {
      layout: { background: { color: c.bg }, textColor: c.text },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      rightPriceScale: { borderColor: c.border }, leftPriceScale: { borderColor: c.border },
      timeScale: { borderColor: c.border },
      crosshair: { vertLine: { color: c.cross, labelBackgroundColor: c.cross }, horzLine: { color: c.cross, labelBackgroundColor: c.cross } },
    };
  };
  // wrap createChart once lightweight-charts has loaded (it is the next script on chart pages)
  var wrap = function () {
    var LC = window.LightweightCharts;
    if (!LC || LC.__clWrapped) return !!LC;
    var orig = LC.createChart;
    var copy = Object.assign({}, LC);
    copy.createChart = function (el, o) {
      var ch = orig.call(LC, el, o);
      try { ch.applyOptions(opts(theme)); charts.push(ch); } catch (e) { /* keep the report working */ }
      return ch;
    };
    copy.__clWrapped = true;
    window.LightweightCharts = copy;
    return true;
  };
  window.__clWrap = wrap;   // called right after the lightweight-charts script tag
  wrap();

  var set = function (t) {
    theme = t;
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("theme", JSON.stringify(t)); } catch (e) { /* private mode */ }
    charts.forEach(function (ch) { try { ch.applyOptions(opts(t)); } catch (e) { /* removed */ } });
    var b = document.getElementById("cl-theme");
    if (b) b.textContent = t === "dark" ? "☾ Night" : "☀ Day";
  };
  window.addEventListener("storage", function (e) { if (e.key === "theme") set(read()); });   // switched in the app

  document.addEventListener("DOMContentLoaded", function () {
    // site-root links of the scanner's own pages point at this route instead (also links its scripts add later)
    var fix = function (root) {
      (root.querySelectorAll ? root.querySelectorAll('a[href^="/"]:not([href^="//"])') : []).forEach(function (a) {
        var h = a.getAttribute("href");
        if (h.indexOf(window.__SCAN_BASE) !== 0) a.setAttribute("href", window.__SCAN_BASE + h.slice(1));
      });
    };
    fix(document);
    new MutationObserver(function (ms) {
      ms.forEach(function (m) { m.addedNodes.forEach(function (n) { if (n.nodeType === 1) { fix(n); if (n.matches && n.matches("a")) fix(n.parentNode); } }); });
    }).observe(document.body, { childList: true, subtree: true });
    var head = document.querySelector("header .row1") || document.querySelector("header");
    if (head) {
      var b = document.createElement("button");
      b.id = "cl-theme"; b.type = "button"; b.title = "Day / night view";
      b.onclick = function () { set(theme === "dark" ? "light" : "dark"); };
      head.appendChild(b);
      set(theme);
    }
  });
})();
