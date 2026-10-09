// Why Academy — Markdown + LaTeX + wikilinks for vault notes
//
// LLM output and PDF text end up in notes, so everything goes through
// DOMPurify before it reaches innerHTML. Math is cut out before Markdown
// parsing (so "_" and "*" inside formulas survive) and rendered by KaTeX
// after sanitizing.

import { marked } from 'https://cdn.jsdelivr.net/npm/marked@18.0.14/lib/marked.esm.js';
import DOMPurify from 'https://cdn.jsdelivr.net/npm/dompurify@3.4.15/dist/purify.es.mjs';
import { WIKILINK } from './model.js';

marked.setOptions({ gfm: true, breaks: true });

// The last branch takes $...$ across lines (not across a blank line) when it
// holds a LaTeX command: equations read from a page often span lines. It
// renders as display math.
const MATH = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|(?<![\\$])\$(?!\s)([^$\n]+?)(?<!\s)\$(?!\d)|(?<![\\$])\$(?!\s)((?:[^$\n]|\n(?![ \t]*\n))*?\\[a-zA-Z](?:[^$\n]|\n(?![ \t]*\n))*?)(?<!\s)\$(?!\d)/g;

export function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function renderMath(tex, display) {
  if (!window.katex) return escapeHtml(tex);
  // Line breaks outside an environment: stack the lines.
  if (display && /\\\\/.test(tex) && !/\\begin\{/.test(tex)) tex = '\\begin{gathered}' + tex + '\\end{gathered}';
  return window.katex.renderToString(tex, { displayMode: display, throwOnError: false, trust: false, strict: 'ignore' });
}

/**
 * Renders note Markdown to safe HTML.
 * resolve(link) -> { label, cls, attrs } describes how a wikilink renders;
 * link is { type: 'anno', id, label } or { type: 'title', title, label }.
 */
export function renderMarkdown(text, resolve) {
  const math = [];
  let src = String(text || '').replace(MATH, (m, dd, sq, rp, inline, multi) => {
    const display = dd !== undefined || sq !== undefined || multi !== undefined;
    math.push({ tex: dd ?? sq ?? rp ?? inline ?? multi, display });
    return `@@MATH${math.length - 1}@@`;
  });

  src = src.replace(WIKILINK, (m, target, label) => {
    target = target.trim();
    const link = target.startsWith('@')
      ? { type: 'anno', id: target.slice(1), label: label ? label.trim() : null }
      : { type: 'title', title: target, label: label ? label.trim() : null };
    const r = resolve(link);
    const attrs = Object.entries(r.attrs || {}).map(([k, v]) => ` data-${k}="${escapeHtml(v)}"`).join('');
    return `<a href="#" class="wl ${r.cls || ''}"${attrs}>${escapeHtml(r.label)}</a>`;
  });

  // Notes have no image storage yet, and remote images in model output would
  // be fetched on render.
  const html = DOMPurify.sanitize(marked.parse(src), { ADD_ATTR: ['target'], FORBID_TAGS: ['img', 'style', 'form'] });
  return html.replace(/@@MATH(\d+)@@/g, (m, i) => renderMath(math[+i].tex, math[+i].display));
}
