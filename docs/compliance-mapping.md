# Compliance mapping

_Generated from `compliance/mapping.yaml` - do not edit by hand._

## Bronze/Silver/Gold pipeline with quarantine table

**Component id:** `medallion_pipeline`

### EU_AI_ACT - Article 10: Data and data governance

Structural validation at the Silver layer, a dedicated quarantine table for non-conforming records, and snapshot identifiers in Gold implement the data-quality and traceability requirements of Article 10.

### BCBS_239 - Principles 3, 4, 6: Accuracy, integrity, completeness, timeliness

Quarantine-based handling of non-conforming records and immutable Delta history support all four data-aggregation principles.

## Gold feature store with Delta time-travel snapshot identifiers

**Component id:** `gold_feature_snapshots`

### EU_AI_ACT - Article 12: Record-keeping

Snapshot identifiers preserve the exact training and inference inputs for any model version, enabling reproducible record-keeping over the lifetime of the system.

## MLflow Model Registry with metric-gated promotion

**Component id:** `mlflow_lifecycle`

### EU_AI_ACT - Article 9: Risk management system

Metric thresholds enforced at promotion implement the risk management gate that Article 9 requires throughout the model lifecycle.

### EU_AI_ACT - Article 17: Quality management system

Versioned registry, documented approver identity, and persisted promotion events provide the documentary substrate of the QMS.

### EBA - : Model risk management lifecycle

Inventory, versioning, independent validation gate, and ongoing monitoring map to the EBA expectations on model risk management.

## Typed governance event store (quarantine, promotion, inference, anchor)

**Component id:** `governance_event_store`

### EU_AI_ACT - Article 12: Record-keeping

Every audit-relevant happening produces a typed event with stable fields suitable for traceback, satisfying the record-keeping duty.

## Merkle batching and on-chain root commitment

**Component id:** `blockchain_anchoring`

### EU_AI_ACT - Article 12: Record-keeping (tamper evidence)

Anchoring the Merkle root in an independent trust domain ensures that records cannot be retroactively altered without detection, strengthening the evidential weight of the Article 12 records.

## Auditor replay tool with four-field structured report

**Component id:** `replay_tool`

### EU_AI_ACT - Article 13: Transparency and provision of information to deployers

Deterministic reconstruction of any past decision, with a structured pass/fail evidence pack, gives deployers and auditors the means to interrogate the system.

## Synthetic SWIFT generator with fixed seed

**Component id:** `synthetic_data`

### GDPR - Articles 5, 25: Data minimisation and data protection by design

Using synthetic data in development avoids unnecessary processing of personal data and demonstrates data protection by design.
