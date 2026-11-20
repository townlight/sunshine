# Documentation export tools

The JavaScript exporters use Node **22.12.0 or later**, `docx`, and Puppeteer.
Install their locked dependencies with `npm ci` from this directory. The browser
is launched headlessly. An existing compatible Chrome can be selected through
`PUPPETEER_EXECUTABLE_PATH`; browser installation can then be skipped with
`PUPPETEER_SKIP_DOWNLOAD=true` during installation.

`generate-deliverables.js` exports the root README and user manual to text, Word
and PDF. It writes those derivatives, so use an isolated copy when checking the
toolchain rather than overwriting maintained or historical editions. The separate
`generate-manual-pdf.js` renders its named local HTML manual.

These dependencies are development documentation tools, not dependencies of the
published Windows runtime. The November 2026 maintenance update removes the
vulnerable Puppeteer 24 browser-download dependency chain and updates Nano ID to
its patched version. It does not replace any released installer or manual.
