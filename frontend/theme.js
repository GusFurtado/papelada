// Loaded in <head> so the saved theme is applied before the first paint. The
// colors themselves live in style.css; `bg` and `accent` here only draw the
// swatches in the picker and the browser's theme-color.
var THEMES = [
  { id: 'midnight', bg: '#0c1016', accent: '#5b9bd5' },
  { id: 'forest', bg: '#0d1511', accent: '#4fb286' },
  { id: 'plum', bg: '#130f18', accent: '#b685e0' },
  { id: 'paper', bg: '#f6f3ec', accent: '#a8561b' },
  { id: 'sky', bg: '#f1f5fa', accent: '#1d6fc2' },
  { id: 'rose', bg: '#fbf3f4', accent: '#b83a5a' }
];

var THEME = (function () {
  var KEY = 'papelada.theme';

  function find(id) {
    for (var i = 0; i < THEMES.length; i++) {
      if (THEMES[i].id === id) return THEMES[i];
    }
    return null;
  }

  function current() {
    var saved = null;
    try { saved = localStorage.getItem(KEY); } catch (e) { /* storage unavailable */ }
    return find(saved) || THEMES[0];
  }

  function apply(id) {
    var theme = find(id) || THEMES[0];
    document.documentElement.setAttribute('data-theme', theme.id);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', theme.bg);
    return theme;
  }

  function set(id) {
    var theme = apply(id);
    try { localStorage.setItem(KEY, theme.id); } catch (e) { /* storage unavailable: just don't remember */ }
    return theme;
  }

  return { current: current, apply: apply, set: set };
})();

THEME.apply(THEME.current().id);
