# Aptos Move Package

This folder is the Aptos Move package used by the thesis prototype.

## Layout

```text
blockchain/
├── Move.toml
├── sources/
│   └── merkle_registry.move
└── tests/
    └── .gitkeep
```

Place the package manifest in `Move.toml`.

Place Move modules in `sources/`. The main module should stay at:

```text
blockchain/sources/merkle_registry.move
```

Use `tests/` later for Move unit tests if we add them.

## Compile

From the repository root:

```powershell
aptos move compile --package-dir blockchain --named-addresses auditable_ai_lakehouse=<YOUR_APTOS_ADDRESS>
```

## Publish To Testnet

```powershell
aptos move publish --profile audit-lakehouse-testnet --package-dir blockchain --named-addresses auditable_ai_lakehouse=<YOUR_APTOS_ADDRESS>
```

The Python orchestrator expects the published module address to be set as:

```powershell
$env:AUDIT_LAKEHOUSE_ANCHORING__MODULE_ADDRESS="<YOUR_APTOS_ADDRESS>"
```
