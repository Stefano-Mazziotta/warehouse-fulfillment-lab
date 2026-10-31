from dataclasses import dataclass

from .ingest_outcome import IngestOutcome


@dataclass
class ReconciliationReport:
    examined: int = 0
    already_known: int = 0
    repaired: int = 0
    conflicts: int = 0
    failed: int = 0

    def record(self, outcome: IngestOutcome) -> None:
        if outcome is IngestOutcome.CREATED:
            self.repaired += 1
        elif outcome is IngestOutcome.CONFLICT:
            self.conflicts += 1
        else:
            self.already_known += 1
