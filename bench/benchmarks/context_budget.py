#!/usr/bin/env python3
"""Simulate N-turn conversation growing toward context limit.
Compare linear (everything in context) vs SAG+folding."""

import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "python-sag", "src"))

from sag.parser import SAGMessageParser
from sag.minifier import MessageMinifier
from sag.fold import FoldEngine


def generate_message(turn: int) -> str:
    """Generate a realistic SAG message for a given turn."""
    src = f"agent{turn % 2}"
    dst = f"agent{(turn + 1) % 2}"
    corr = f" corr=msg{turn - 1}" if turn > 0 else ""
    stmts = [f'DO action{turn}("argument_{turn}", detail="This is turn {turn} of the conversation with some realistic content")']
    if turn % 3 == 0:
        stmts.append(f'A state.turn = {turn}; A state.progress = {turn * 5}')
    body = "; ".join(stmts)
    return f"H v 1 id=msg{turn} src={src} dst={dst} ts={1000 + turn}{corr}\n{body}"


def run():
    print("=" * 80)
    print("CONTEXT BUDGET SIMULATION")
    print("=" * 80)
    print()

    budget = 10000  # 10K token budget (simulates smaller context windows)
    threshold = 0.7
    max_turns = 2000

    # Linear: just accumulate everything
    linear_tokens = []
    linear_cumulative = 0

    # SAG+Fold: fold when approaching threshold
    fold_engine = FoldEngine()
    fold_messages_raw = []  # Current unfolded messages
    fold_active_folds = []  # Active fold summaries
    fold_tokens = []
    fold_cumulative = 0

    results = []

    for turn in range(max_turns):
        msg_text = generate_message(turn)
        msg_tokens = MessageMinifier.count_tokens(msg_text)

        # LINEAR: just add
        linear_cumulative += msg_tokens
        linear_tokens.append(linear_cumulative)

        # SAG+FOLD: add, then check if we need to fold
        fold_messages_raw.append(msg_text)
        fold_cumulative += msg_tokens

        # Check if we should fold
        if fold_cumulative >= budget * threshold and len(fold_messages_raw) > 2:
            # Fold all but the last 2 messages
            to_fold = fold_messages_raw[:-2]
            parsed = [SAGMessageParser.parse(m) for m in to_fold]
            fold_stmt = fold_engine.fold(parsed, f"Turns {turn - len(to_fold) + 1}-{turn - 2} summary")

            # Replace folded messages with a single fold statement
            fold_msg = f'H v 1 id=fold{turn} src=system dst=system ts={2000 + turn}\nFOLD {fold_stmt.fold_id} "Summary of turns"'
            fold_token_count = MessageMinifier.count_tokens(fold_msg)

            # Calculate new cumulative: fold summaries + remaining raw messages
            fold_cumulative = fold_token_count
            for fm in fold_active_folds:
                fold_cumulative += fm
            remaining = fold_messages_raw[-2:]
            for rm in remaining:
                fold_cumulative += MessageMinifier.count_tokens(rm)

            fold_active_folds.append(fold_token_count)
            fold_messages_raw = remaining

        fold_tokens.append(fold_cumulative)

        if turn % 50 == 0 or linear_cumulative >= budget or turn == max_turns - 1:
            row = {
                "turn": turn,
                "linear_tokens": linear_cumulative,
                "fold_tokens": fold_cumulative,
                "linear_pct": f"{linear_cumulative / budget * 100:.1f}%",
                "fold_pct": f"{fold_cumulative / budget * 100:.1f}%",
                "active_folds": fold_engine.get_fold_count(),
            }
            results.append(row)

        if linear_cumulative >= budget and fold_cumulative >= budget:
            break

    # Find when each hits budget
    linear_exhausted = next((i for i, t in enumerate(linear_tokens) if t >= budget), max_turns)
    fold_exhausted = next((i for i, t in enumerate(fold_tokens) if t >= budget), max_turns)

    print(f"Context budget: {budget:,} tokens")
    print(f"Fold threshold: {threshold * 100:.0f}%")
    print()
    print(f"{'Turn':>6} {'Linear':>12} {'Linear %':>10} {'SAG+Fold':>12} {'Fold %':>10} {'Folds':>6}")
    print("-" * 60)
    for r in results:
        print(
            f"{r['turn']:>6} {r['linear_tokens']:>12,} {r['linear_pct']:>10} "
            f"{r['fold_tokens']:>12,} {r['fold_pct']:>10} {r['active_folds']:>6}"
        )
    print()
    print(f"Linear exhausts budget at turn: {linear_exhausted}")
    print(f"SAG+Fold exhausts budget at turn: {fold_exhausted}")
    if linear_exhausted > 0:
        print(f"SAG+Fold enables {fold_exhausted / linear_exhausted:.1f}x more turns")

    # Write CSV
    reports_dir = os.path.join(os.path.dirname(__file__), "..", "reports")
    os.makedirs(reports_dir, exist_ok=True)
    csv_path = os.path.join(reports_dir, "context_budget.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["turn", "linear_tokens", "fold_tokens"])
        for i in range(min(len(linear_tokens), len(fold_tokens))):
            writer.writerow([i, linear_tokens[i], fold_tokens[i]])
    print(f"\nCSV written to {csv_path}")

    # Try chart
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(12, 6))
        turns = list(range(len(linear_tokens)))
        ax.plot(turns, linear_tokens, label="Linear (no folding)", color="#FF5722", linewidth=2)
        ax.plot(turns[: len(fold_tokens)], fold_tokens, label="SAG + Folding", color="#2196F3", linewidth=2)
        ax.axhline(y=budget, color="red", linestyle="--", alpha=0.5, label=f"Budget ({budget:,} tokens)")
        ax.axhline(y=budget * threshold, color="orange", linestyle=":", alpha=0.5, label=f"Fold threshold ({threshold * 100:.0f}%)")

        ax.set_xlabel("Conversation Turn")
        ax.set_ylabel("Context Tokens")
        ax.set_title("Context Budget: Linear vs SAG+Folding")
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()

        chart_path = os.path.join(reports_dir, "context_budget.png")
        plt.savefig(chart_path, dpi=150)
        print(f"Chart saved to {chart_path}")
    except ImportError:
        print("matplotlib not available, skipping chart generation")


if __name__ == "__main__":
    run()
