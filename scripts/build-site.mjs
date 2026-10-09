// Copies the public site into dist/ for the Cloudflare Worker's static assets.
// Only git-tracked files under the allowlisted paths ship, so local scratch
// files (backups, gitignored notes) are never deployed.

import { execFileSync } from 'node:child_process';
import { cpSync, rmSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = join(ROOT, 'dist');

export const PUBLIC_PATHS = [
  'index.html',
  'lesson.html',
  'playground.html',
  'rootlock.html',
  'reader.html',
  'app.js',
  'playground.js',
  'rootlock.js',
  'reader.js',
  'style.css',
  'rootlock.css',
  'reader.css',
  'lib',
  'lessons',
];

const files = execFileSync('git', ['ls-files', '-z', '--', ...PUBLIC_PATHS], { cwd: ROOT, encoding: 'utf8' })
  .split('\0')
  .filter(Boolean);
if (files.length === 0) throw new Error('git ls-files returned no public files');

rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT);
for (const f of files) {
  mkdirSync(dirname(join(OUT, f)), { recursive: true });
  cpSync(join(ROOT, f), join(OUT, f));
}
// Which code a bug report came from.
const commit = execFileSync('git', ['rev-parse', '--short', 'HEAD'], { cwd: ROOT, encoding: 'utf8' }).trim();
const dirty = execFileSync('git', ['status', '--porcelain', '--', ...PUBLIC_PATHS], { cwd: ROOT, encoding: 'utf8' }).trim() !== '';
writeFileSync(join(OUT, 'build.json'), JSON.stringify({ commit, dirty, builtAt: new Date().toISOString() }));

console.log('Built dist/ with', files.length, 'tracked files');
