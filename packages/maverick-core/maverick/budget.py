"""Budget tracking. Long-horizon agents need hard caps."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


class BudgetExceeded(Exception):
    pass


@dataclass
class Budget:
    max_input_tokens: int = 1_000_000
    max_output_tokens: int = 200_000
    max_dollars: float = 5.0
    max_wall_seconds: float = 3600.0
    max_tool_calls: int = 500

    input_tokens: int = 0
    output_tokens: int = 0
    dollars: float = 0.0
    tool_calls: int = 0
    started_at: float = field(default_factory=time.time)

    # Approximate per-million-token prices. Override per model if needed.
    price_in_per_mtok: float = 3.0
    price_out_per_mtok: float = 15.0

    def record_tokens(self, in_tok: int, out_tok: int) -> None:
        self.input_tokens += in_tok
        self.output_tokens += out_tok
        self.dollars += (in_tok / 1_000_000) * self.price_in_per_mtok
        self.dollars += (out_tok / 1_000_000) * self.price_out_per_mtok
        self.check()

    def record_tool_call(self) -> None:
        self.tool_calls += 1
        self.check()

    def elapsed(self) -> float:
        return time.time() - self.started_at

    def check(self) -> None:
        if self.input_tokens > self.max_input_tokens:
            raise BudgetExceeded(f"input tokens {self.input_tokens} > {self.max_input_tokens}")
        if self.output_tokens > self.max_output_tokens:
            raise BudgetExceeded(f"output tokens {self.output_tokens} > {self.max_output_tokens}")
        if self.dollars > self.max_dollars:
            raise BudgetExceeded(f"${self.dollars:.2f} > ${self.max_dollars:.2f}")
        if self.tool_calls > self.max_tool_calls:
            raise BudgetExceeded(f"tool calls {self.tool_calls} > {self.max_tool_calls}")
        if self.elapsed() > self.max_wall_seconds:
            raise BudgetExceeded(f"wall time {self.elapsed():.0f}s > {self.max_wall_seconds:.0f}s")

    def summary(self) -> str:
        return (
            f"tokens in={self.input_tokens} out={self.output_tokens} "
            f"$={self.dollars:.3f} tools={self.tool_calls} wall={self.elapsed():.0f}s"
        )
