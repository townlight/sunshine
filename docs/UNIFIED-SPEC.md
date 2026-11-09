# Townlight Records — specification and current source map

Townlight Beta 1 component (AGPL-3.0-only): `townlight-records` 1.8.0.dev2, principal import
`townlight_records`, paired with `townlight-core` 1.3.0.dev2. Windows MSI 1.8.0.1 is published. Its exact acceptance summary is at https://github.com/townlight/townlight/releases/download/townlight-windows-v1.8.0.1/ACCEPTANCE-Windows-1.8.0.1.md; standalone deployment remains separate.

The [complete retained design specification](history/pre-naming-2026-11/docs/UNIFIED-SPEC.md)
preserves its original text, identities, phase labels and dated release/test
claims. This index does not remove its product requirements. Those implementation
and completion labels describe the recorded versions; they are not proof for
this changed candidate. The approved naming/fresh-install decisions supersede
its old distribution, import and upgrade assumptions.

Use the [current operating manual](../USER-MANUAL.md) for the bounded Windows
workflow and its deployment limits. The [current API reference](beta-1/api/records.html)
and [generated OpenAPI schema](openapi.json) describe the current source routes;
the [source inventory](beta-1/reference/index.html) identifies the inspected files.
The [README](../README.md) provides exact local-wheel installation instructions.

The native Windows product and the standalone Compose deployment have different
installation paths. The coordinated Windows MSI uses the native runtime, a fresh
empty database/profile and the approved existing profile-directory spelling.
There is no in-place legacy database upgrade or old-import compatibility shim.
Historical Inno installers and their original receipts are not renamed.
