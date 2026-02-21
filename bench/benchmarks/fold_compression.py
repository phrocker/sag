#!/usr/bin/env python3
"""Measure compression ratios at various fold granularities."""

import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "python-sag", "src"))

from sag.parser import SAGMessageParser
from sag.minifier import MessageMinifier
from sag.fold import FoldEngine


def generate_conversation(n_messages: int) -> list[str]:
    """Generate a synthetic N-message conversation."""
    messages = []
    for i in range(n_messages):
        src = f"agent{i % 3}"
        dst = f"agent{(i + 1) % 3}"
        corr = f" corr=msg{i-1}" if i > 0 else ""
        stmts = [
            f'DO action{i}("arg{i}", count={i * 10})',
            f'A state.step = {i}',
        ]
        body = "; ".join(stmts)
        msg = f"H v 1 id=msg{i} src={src} dst={dst} ts={1000 + i}{corr}\n{body}"
        messages.append(msg)
    return messages


def measure_tokens(messages: list[str]) -> int:
    """Count total tokens across all messages."""
    total = 0
    for msg in messages:
        total += MessageMinifier.count_tokens(msg)
    return total


def fold_messages(messages: list[str], fold_size: int) -> list[str]:
    """Fold messages in groups of fold_size, replacing each group with a FOLD statement."""
    engine = FoldEngine()
    result = []

    for i in range(0, len(messages), fold_size):
        group = messages[i : i + fold_size]
        if len(group) >= 2:
            # Parse to get Message objects for fold
            parsed = [SAGMessageParser.parse(m) for m in group]
            fold_stmt = engine.fold(parsed, f"Folded messages {i}-{i + len(group) - 1}")
            # Create a fold message
            fold_msg = f'H v 1 id=fold{i} src=system dst=system ts={2000 + i}\nFOLD {fold_stmt.fold_id} "Folded messages {i}-{i + len(group) - 1}"'
            result.append(fold_msg)
        else:
            result.extend(group)

    return result


def run():
    print("=" * 80)
    print("FOLD COMPRESSION BENCHMARK")
    print("=" * 80)
    print()

    conversation_sizes = [10, 25, 50, 100, 200]
    fold_sizes = [5, 10, 25, 50]

    results = []

    print(f"{'Conv Size':>10} {'Fold Size':>10} {'Original':>10} {'Folded':>10} {'Ratio':>10} {'Savings':>10}")
    print("-" * 65)

    for conv_size in conversation_sizes:
        messages = generate_conversation(conv_size)
        original_tokens = measure_tokens(messages)

        for fold_size in fold_sizes:
            if fold_size >= conv_size:
                continue

            folded = fold_messages(messages, fold_size)
            folded_tokens = measure_tokens(folded)
            ratio = folded_tokens / original_tokens if original_tokens > 0 else 0
            savings = (1 - ratio) * 100

            row = {
                "conversation_size": conv_size,
                "fold_size": fold_size,
                "original_tokens": original_tokens,
                "folded_tokens": folded_tokens,
                "compression_ratio": f"{ratio:.3f}",
                "savings_percent": f"{savings:.1f}%",
            }
            results.append(row)

            print(
                f"{conv_size:>10} {fold_size:>10} {original_tokens:>10} {folded_tokens:>10} "
                f"{ratio:>10.3f} {savings:>9.1f}%"
            )

    print()

    # Write CSV
    reports_dir = os.path.join(os.path.dirname(__file__), "..", "reports")
    os.makedirs(reports_dir, exist_ok=True)
    csv_path = os.path.join(reports_dir, "fold_compression.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    print(f"CSV written to {csv_path}")

    # Try chart
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 6))

        for fold_size in fold_sizes:
            xs = [r["conversation_size"] for r in results if r["fold_size"] == fold_size]
            ys = [float(r["compression_ratio"]) for r in results if r["fold_size"] == fold_size]
            if xs:
                ax.plot(xs, ys, marker="o", label=f"Fold every {fold_size}")

        ax.set_xlabel("Conversation Length (messages)")
        ax.set_ylabel("Compression Ratio (lower = better)")
        ax.set_title("Fold Compression Ratio vs Conversation Length")
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()

        chart_path = os.path.join(reports_dir, "fold_compression.png")
        plt.savefig(chart_path, dpi=150)
        print(f"Chart saved to {chart_path}")
    except ImportError:
        print("matplotlib not available, skipping chart generation")


if __name__ == "__main__":
    run()
