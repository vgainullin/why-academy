// Why Academy — export a paper with its annotations drawn in
//
// Ink strokes, highlights and region boxes are drawn onto the original PDF
// with pdf-lib, so the file opens with marks in any PDF viewer (for sharing
// at journal club). Positions come from pdf.js viewports, which account for
// page rotation and crop boxes.

import { PDFDocument, rgb, BlendMode, LineCapStyle } from 'https://cdn.jsdelivr.net/npm/pdf-lib@1.17.1/dist/pdf-lib.esm.min.js';

function color(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
  const n = m ? parseInt(m[1], 16) : 0x1f2937;
  return rgb(((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255);
}

/**
 * bytes: the original PDF. view: an opened PdfView (for its pdf.js document).
 * annos, inks: vault items of the paper. Returns the annotated PDF bytes.
 */
export async function exportAnnotatedPdf(bytes, view, { annos, inks }) {
  const out = await PDFDocument.load(bytes, { ignoreEncryption: true });
  const pages = out.getPages();

  // Normalized page coordinates (0..1, origin top-left, as displayed) to PDF
  // user space for page n, via the pdf.js viewport at scale 1.
  const mappers = new Map();
  const mapper = async n => {
    if (!mappers.has(n)) {
      const vp = (await view.pdf.getPage(n)).getViewport({ scale: 1 });
      mappers.set(n, {
        width: vp.width,
        at: (u, v) => {
          const [x, y] = vp.convertToPdfPoint(u * vp.width, v * vp.height);
          return { x, y };
        },
      });
    }
    return mappers.get(n);
  };

  for (const a of annos) {
    const page = pages[a.data.page - 1];
    if (!page) continue;
    const m = await mapper(a.data.page);
    for (const [x, y, w, h] of a.data.rects) {
      const c = [m.at(x, y), m.at(x + w, y), m.at(x, y + h), m.at(x + w, y + h)];
      const xs = c.map(p => p.x), ys = c.map(p => p.y);
      const rect = { x: Math.min(...xs), y: Math.min(...ys), width: Math.max(...xs) - Math.min(...xs), height: Math.max(...ys) - Math.min(...ys) };
      if (a.data.type === 'highlight') {
        page.drawRectangle({ ...rect, color: color(a.data.color), opacity: 0.4, blendMode: BlendMode.Multiply });
      } else {
        page.drawRectangle({ ...rect, borderColor: color('#2563eb'), borderWidth: 1.2, borderOpacity: 0.9 });
      }
    }
  }

  for (const ink of inks) {
    const page = pages[ink.data.page - 1];
    if (!page) continue;
    const m = await mapper(ink.data.page);
    for (const s of ink.data.strokes) {
      const p = s.points;
      const base = s.width * m.width;
      const hl = s.tool === 'highlighter';
      const style = hl
        ? { color: color(s.color), opacity: 0.35, blendMode: BlendMode.Multiply, lineCap: LineCapStyle.Butt }
        : { color: color(s.color), opacity: 1, lineCap: LineCapStyle.Round };
      if (p.length === 3) {
        const c = m.at(p[0], p[1]);
        page.drawCircle({ x: c.x, y: c.y, size: base / 2, color: style.color, opacity: style.opacity });
        continue;
      }
      for (let i = 3; i < p.length; i += 3) {
        const thickness = hl ? base : base * (0.6 + p[i + 2] * 0.8);
        page.drawLine({ start: m.at(p[i - 3], p[i - 2]), end: m.at(p[i], p[i + 1]), thickness, ...style });
      }
    }
  }

  return out.save();
}

// Shares (iPad share sheet: AirDrop, Mail, Files) or downloads the file.
export async function deliverPdf(bytes, filename) {
  const file = new File([bytes], filename, { type: 'application/pdf' });
  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title: filename });
      return 'shared';
    } catch (e) {
      if (e.name === 'AbortError') return 'cancelled';
      console.warn('Sharing failed, downloading instead', e);
    }
  }
  const url = URL.createObjectURL(file);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
  return 'downloaded';
}
