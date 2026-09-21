# Backup and recovery · fictional sample

The figures below are demonstration data for an imaginary service, not recovery commitments for a real product.

## Backup schedule

The primary database takes an encrypted snapshot every six hours. Snapshots are retained for 30 days in a separate region. A daily job checks snapshot creation and reports missing backups to the on-call team.

## Restore testing

Restore a recent snapshot into an isolated test environment once a month. The test must verify record counts, application login, and a representative read and write operation. Record the restore duration and any failed checks in the recovery log. A failed restore test creates a high-priority remediation ticket.

## Recovery targets

The demonstration recovery time objective is four hours. The demonstration recovery point objective is six hours. These targets are checked during quarterly disaster recovery exercises and adjusted when the service architecture changes.
