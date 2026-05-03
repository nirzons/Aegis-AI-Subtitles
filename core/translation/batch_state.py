from dataclasses import dataclass, field
from typing import List

@dataclass
class BatchState:
    current_batch_size: int
    effective_batch_size: int
    success_streak: int = 0
    failures_at_current_size: int = 0
    min_batch_failures: int = 0
    attempted_batch_sizes: List[int] = field(default_factory=list)
    batch_success: bool = False
