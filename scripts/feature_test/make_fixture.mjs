// Writes a small multi-page "paper" PDF for feature tests: a title, an
// abstract, sections, numbered equations and a reference list, so every
// reader action (select, region, equation card, explain) has real targets.
// Usage: node make_fixture.mjs <out.pdf>

import { writeFileSync } from 'node:fs';

const PAGES = [
  [
    ['title', 'Scaled Dot-Product Attention: A Short Derivation'],
    ['author', 'A. Tester and B. Reader'],
    ['h', 'Abstract'],
    ['p', 'We derive why dot-product attention divides the logits by the square root of the key'],
    ['p', 'dimension. Without the scale, the variance of the logits grows linearly with d_k,'],
    ['p', 'softmax saturates, and gradients vanish. We give the variance argument and a numeric check.'],
    ['h', '1  Introduction'],
    ['p', 'An attention layer maps queries Q, keys K and values V to a weighted sum of the values.'],
    ['p', 'The weights come from a softmax over query-key similarities:'],
    ['eq', 'Attention(Q, K, V) = softmax( Q K^T / sqrt(d_k) ) V', '(1)'],
    ['p', 'The factor 1/sqrt(d_k) is the subject of this note. It is easy to overlook and easy to'],
    ['p', 'get wrong when re-implementing the layer.'],
  ],
  [
    ['h', '2  Variance of a dot product'],
    ['p', 'Let the components q_i and k_i be independent with mean 0 and variance 1. Then'],
    ['eq', 'q . k = sum_{i=1}^{d_k} q_i k_i', '(2)'],
    ['p', 'Each term q_i k_i has mean 0 and variance E[q_i^2] E[k_i^2] = 1, so by independence'],
    ['eq', 'Var(q . k) = d_k', '(3)'],
    ['p', 'Dividing by sqrt(d_k) restores unit variance:'],
    ['eq', 'Var( q . k / sqrt(d_k) ) = d_k / d_k = 1', '(4)'],
    ['h', '3  Why saturation hurts'],
    ['p', 'For logits z with large spread, softmax(z) approaches a one-hot vector and its Jacobian'],
    ['eq', 'd softmax_i / d z_j = s_i (delta_ij - s_j)', '(5)'],
    ['p', 'goes to zero almost everywhere, so little gradient reaches Q and K.'],
  ],
  [
    ['h', '4  Numeric check'],
    ['p', 'With d_k = 512 and unit-variance inputs, unscaled logits have standard deviation near 22.6;'],
    ['p', 'the largest softmax weight then exceeds 0.99 in most rows. Scaled logits have standard'],
    ['p', 'deviation near 1 and the weights stay spread out.'],
    ['h', '5  Discussion'],
    ['p', 'Other choices, such as learned temperatures or normalizing Q and K, address the same'],
    ['p', 'problem. Open question for discussion: does the argument still hold when q and k are'],
    ['p', 'correlated, as they are after training?'],
    ['h', 'References'],
    ['p', '[1] Vaswani et al. Attention Is All You Need. NeurIPS 2017.'],
    ['p', '[2] Glorot and Bengio. Understanding the difficulty of training deep feedforward networks. 2010.'],
  ],
];

const STYLE = {
  title: { font: 'F2', size: 18, gap: 30 },
  author: { font: 'F1', size: 11, gap: 28 },
  h: { font: 'F2', size: 13, gap: 24 },
  p: { font: 'F1', size: 10.5, gap: 15 },
  eq: { font: 'F3', size: 11, gap: 26 },
};

const esc = s => s.replace(/[\\()]/g, c => '\\' + c);

function pageStream(blocks, num) {
  let y = 740;
  const ops = [];
  for (const [kind, text, label] of blocks) {
    const st = STYLE[kind];
    if (kind === 'h' || kind === 'eq') y -= 6;
    const x = kind === 'eq' ? 110 : kind === 'title' || kind === 'author' ? 72 : 72;
    ops.push(`BT /${st.font} ${st.size} Tf ${x} ${y} Td (${esc(text)}) Tj ET`);
    if (label) ops.push(`BT /F1 ${st.size} Tf 520 ${y} Td (${label}) Tj ET`);
    y -= st.gap;
  }
  ops.push(`BT /F1 9 Tf 300 40 Td (${num}) Tj ET`);
  return ops.join('\n');
}

const objs = [];
const add = body => objs.push(body) && objs.length;
const catalog = add('<< /Type /Catalog /Pages 2 0 R >>');
const pagesIdx = add('PAGES');
const f1 = add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>');
const f2 = add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>');
const f3 = add('<< /Type /Font /Subtype /Type1 /BaseFont /Times-Italic >>');
const kids = [];
PAGES.forEach((blocks, i) => {
  const s = pageStream(blocks, i + 1);
  const content = add(`<< /Length ${Buffer.byteLength(s)} >>\nstream\n${s}\nendstream`);
  kids.push(add(`<< /Type /Page /Parent ${pagesIdx} 0 R /MediaBox [0 0 612 792] /Contents ${content} 0 R ` +
    `/Resources << /Font << /F1 ${f1} 0 R /F2 ${f2} 0 R /F3 ${f3} 0 R >> >> >>`));
});
objs[pagesIdx - 1] = `<< /Type /Pages /Kids [${kids.map(k => k + ' 0 R').join(' ')}] /Count ${kids.length} >>`;
const info = add('<< /Title (Scaled Dot-Product Attention: A Short Derivation) /Author (A. Tester) >>');

let out = '%PDF-1.4\n';
const offsets = [];
objs.forEach((o, i) => {
  offsets.push(Buffer.byteLength(out));
  out += `${i + 1} 0 obj\n${o}\nendobj\n`;
});
const xref = Buffer.byteLength(out);
out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offsets.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
out += `trailer\n<< /Size ${objs.length + 1} /Root ${catalog} 0 R /Info ${info} 0 R >>\nstartxref\n${xref}\n%%EOF\n`;

if (!process.argv[2]) throw new Error('usage: node make_fixture.mjs <out.pdf>');
writeFileSync(process.argv[2], out, 'latin1');
