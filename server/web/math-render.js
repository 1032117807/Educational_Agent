(function () {
  'use strict';

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, character => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    })[character]);
  }

  function normalizeMath(value) {
    const text = String(value ?? '').replace(/\r\n?/g, '\n');
    // Models sometimes emit a bare TeX command. Keep ordinary prose untouched,
    // but make an un-delimited formula renderable by MathJax.
    if (!/\\(?:frac|sqrt|sum|prod|lim|int|begin|alpha|beta|theta|leq|geq)\b/.test(text)) return text;
    if (text.includes('\\(') || text.includes('\\[') || text.includes('$$') || /\$[^$]+\$/.test(text)) return text;
    return `\\(${text}\\)`;
  }

  window.mathHtml = function (value) {
    return escapeHtml(normalizeMath(value)).replace(/\n/g, '<br>');
  };

  window.typesetMath = function (root) {
    if (!root || !window.MathJax?.typesetPromise) return Promise.resolve();
    return window.MathJax.typesetPromise([root]).catch(() => {});
  };
})();
