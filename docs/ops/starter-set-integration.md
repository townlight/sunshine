<a id="civicsunshine-starter-set-integration"></a>

# Townlight Records Starter-Set Integration

Status: maintained module-side proof helper for the Townlight Core + Townlight Records + Townlight Meetings starter set.

The umbrella installer owns the generated starter-set packages. Townlight Records
owns the module contract it contributes to that package: version, Townlight Core
runtime pin, selectability, and honest boundary language.

Run the module-side check from this repo:

```powershell
python scripts\check_starter_set_integration.py --umbrella-root ..\civicsuite --require-archives
```

The check verifies that:

- the umbrella `clerk-core` profile installs Townlight Core first, then Townlight Records
  AI, then Townlight Meetings;
- Townlight Records is selectable at v1.6.1 and records the Townlight Core 1.0.1
  runtime dependency used by the current module release;
- Townlight Meetings is paired at v1.0.1;
- the umbrella release contract requires package workflow proof with
  `--staff-mode bearer --workflow-proof`;
- Linux and Windows starter-set release archives exist when
  `--require-archives` is used.

This is starter-set install/test evidence. It is not a claim that Townlight Records
AI and Townlight Meetings exchange live workflow records through a cross-module
business API yet, and it is not macOS lifecycle certification.
