// Current source renderer; the original fixed/versioned template is preserved under docs/history.
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const result = spawnSync(process.env.PYTHON || 'python',
  [path.join(__dirname, 'build_current_documents.py'), '--documents', 'spec', ...process.argv.slice(2)],
  { stdio: 'inherit' });
if (result.error) { console.error(result.error.message); process.exit(1); }
process.exit(result.status ?? 1);
