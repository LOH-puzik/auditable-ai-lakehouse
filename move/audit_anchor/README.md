# Aptos Move Package: AuditAnchor

This folder is the Aptos Move package used by the thesis prototype.

## Layout

```text
move/audit_anchor/
├── Move.toml
├── sources/
│   └── audit_anchor.move
└── tests/
    └── .gitkeep
```

Place the package manifest in `Move.toml`.

Place Move modules in `sources/`. The main module should stay at:

```text
move/audit_anchor/sources/audit_anchor.move
```

Use `tests/` later for Move unit tests if we add them.

## Compile

From the repository root:

```powershell
aptos move compile --package-dir move/audit_anchor --named-addresses audit_anchor=<YOUR_APTOS_ADDRESS>
```

## Publish To Devnet

```powershell
aptos move publish --profile swift-audit-devnet --package-dir move/audit_anchor --named-addresses audit_anchor=<YOUR_APTOS_ADDRESS>
```

The Python orchestrator expects the published module address to be set as:

```powershell
$env:SWIFT_AUDIT_ANCHORING__MODULE_ADDRESS="<YOUR_APTOS_ADDRESS>"
```
