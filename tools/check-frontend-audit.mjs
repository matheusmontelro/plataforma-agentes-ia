#!/usr/bin/env node

import { spawnSync } from 'node:child_process';
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const frontendRoot = join(projectRoot, 'frontend');
const sourceRoot = join(frontendRoot, 'src');

// React Router ainda não publicou uma versão 7.x corrigida para este aviso.
// A exceção é segura somente para este SPA, que não usa as APIs RSC instáveis
// explicitamente indicadas pelo aviso como pré-requisito de exploração.
const allowedAdvisories = new Set([
  'https://github.com/advisories/GHSA-qwww-vcr4-c8h2',
]);
const allowedPackages = new Set(['react-router', 'react-router-dom']);
const rscMarkers = [
  /\bunstable_[A-Za-z0-9_]+/,
  /\bcreateRequestHandler\b/,
  /\bServerRouter\b/,
  /\bmatchRSC\b/,
  /\brouteRSC\b/,
];

function sourceFiles(directory) {
  const files = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...sourceFiles(path));
    } else if (['.js', '.jsx', '.ts', '.tsx'].includes(extname(entry.name))) {
      files.push(path);
    }
  }
  return files;
}

const audit = spawnSync('npm', ['audit', '--json'], {
  cwd: frontendRoot,
  encoding: 'utf8',
});

let report;
try {
  report = JSON.parse(audit.stdout || '');
} catch {
  process.stderr.write(audit.stderr || audit.stdout || 'npm audit não retornou JSON válido.\n');
  process.exit(1);
}

const severeEntries = Object.values(report.vulnerabilities || {}).filter(
  (entry) => entry && ['high', 'critical'].includes(entry.severity),
);

if (severeEntries.length === 0) {
  console.log('Frontend audit passed: no high or critical vulnerabilities.');
  process.exit(0);
}

const unexpectedPackages = severeEntries
  .map((entry) => entry.name)
  .filter((name) => !allowedPackages.has(name));
const advisories = severeEntries.flatMap((entry) =>
  Array.isArray(entry.via) ? entry.via.filter((item) => typeof item === 'object') : [],
);
const unexpectedAdvisories = advisories.filter(
  (advisory) => !allowedAdvisories.has(advisory.url),
);

if (unexpectedPackages.length > 0 || unexpectedAdvisories.length > 0) {
  console.error('Frontend audit failed: high or critical vulnerability outside the reviewed exception.');
  for (const name of new Set(unexpectedPackages)) console.error(`- package: ${name}`);
  for (const advisory of unexpectedAdvisories) console.error(`- advisory: ${advisory.url || advisory.title}`);
  process.exit(1);
}

const rscUsage = [];
for (const path of sourceFiles(sourceRoot)) {
  const content = readFileSync(path, 'utf8');
  if (rscMarkers.some((pattern) => pattern.test(content))) {
    rscUsage.push(path.slice(projectRoot.length + 1));
  }
}

if (rscUsage.length > 0) {
  console.error('Frontend audit failed: the React Router RSC exception is invalid because RSC markers were found.');
  for (const path of rscUsage) console.error(`- ${path}`);
  process.exit(1);
}

console.log(
  'Frontend audit passed with reviewed exception GHSA-qwww-vcr4-c8h2: this SPA does not use unstable RSC APIs.',
);
