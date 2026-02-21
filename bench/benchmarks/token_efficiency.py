#!/usr/bin/env python3
"""Compare token counts across SAG, JSON, and natural language formats."""

import csv
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "python-sag", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fixtures.conversations import CONVERSATIONS


def chars_to_tokens(text: str) -> int:
    """Approximate token count using chars/4 heuristic."""
    import math
    return math.ceil(len(text) / 4.0)


def try_tiktoken(text: str) -> int | None:
    """Try to count tokens with tiktoken if available."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return None


def run():
    print("=" * 80)
    print("TOKEN EFFICIENCY BENCHMARK: SAG vs JSON vs Natural Language")
    print("=" * 80)
    print()

    results = []
    totals = {"sag_chars": 0, "json_chars": 0, "nl_chars": 0, "sag_tokens": 0, "json_tokens": 0, "nl_tokens": 0}

    for conv in CONVERSATIONS:
        sag_text = "\n".join(conv["sag"])
        json_text = "\n".join(conv["json"])
        nl_text = "\n".join(conv["nl"])

        sag_chars = len(sag_text)
        json_chars = len(json_text)
        nl_chars = len(nl_text)

        sag_tokens = chars_to_tokens(sag_text)
        json_tokens = chars_to_tokens(json_text)
        nl_tokens = chars_to_tokens(nl_text)

        # Try tiktoken for more accurate counts
        sag_tiktoken = try_tiktoken(sag_text)
        json_tiktoken = try_tiktoken(json_text)
        nl_tiktoken = try_tiktoken(nl_text)

        row = {
            "name": conv["name"],
            "messages": len(conv["sag"]),
            "sag_chars": sag_chars,
            "json_chars": json_chars,
            "nl_chars": nl_chars,
            "sag_tokens_heuristic": sag_tokens,
            "json_tokens_heuristic": json_tokens,
            "nl_tokens_heuristic": nl_tokens,
            "sag_tokens_tiktoken": sag_tiktoken,
            "json_tokens_tiktoken": json_tiktoken,
            "nl_tokens_tiktoken": nl_tiktoken,
            "sag_vs_json_savings": f"{((json_chars - sag_chars) / json_chars * 100):.1f}%",
            "sag_vs_nl_savings": f"{((nl_chars - sag_chars) / nl_chars * 100):.1f}%",
        }
        results.append(row)

        totals["sag_chars"] += sag_chars
        totals["json_chars"] += json_chars
        totals["nl_chars"] += nl_chars
        totals["sag_tokens"] += sag_tokens
        totals["json_tokens"] += json_tokens
        totals["nl_tokens"] += nl_tokens

    # Print table
    print(f"{'Conversation':<35} {'Msgs':>5} {'SAG':>8} {'JSON':>8} {'NL':>8} {'SAG vs JSON':>12} {'SAG vs NL':>10}")
    print("-" * 90)
    for r in results:
        print(
            f"{r['name']:<35} {r['messages']:>5} {r['sag_chars']:>8} {r['json_chars']:>8} {r['nl_chars']:>8} "
            f"{r['sag_vs_json_savings']:>12} {r['sag_vs_nl_savings']:>10}"
        )
    print("-" * 90)

    total_sag_vs_json = (totals["json_chars"] - totals["sag_chars"]) / totals["json_chars"] * 100
    total_sag_vs_nl = (totals["nl_chars"] - totals["sag_chars"]) / totals["nl_chars"] * 100
    print(
        f"{'TOTAL':<35} {'':>5} {totals['sag_chars']:>8} {totals['json_chars']:>8} {totals['nl_chars']:>8} "
        f"{total_sag_vs_json:>11.1f}% {total_sag_vs_nl:>9.1f}%"
    )
    print()
    print(f"Approximate tokens (chars/4): SAG={totals['sag_tokens']}, JSON={totals['json_tokens']}, NL={totals['nl_tokens']}")
    print()

    # Write CSV
    reports_dir = os.path.join(os.path.dirname(__file__), "..", "reports")
    os.makedirs(reports_dir, exist_ok=True)
    csv_path = os.path.join(reports_dir, "token_efficiency.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    print(f"CSV written to {csv_path}")

    # Try to generate chart
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        names = [r["name"][:20] for r in results]
        sag_vals = [r["sag_chars"] for r in results]
        json_vals = [r["json_chars"] for r in results]
        nl_vals = [r["nl_chars"] for r in results]

        x = np.arange(len(names))
        width = 0.25

        fig, ax = plt.subplots(figsize=(14, 6))
        ax.bar(x - width, sag_vals, width, label="SAG", color="#2196F3")
        ax.bar(x, json_vals, width, label="JSON", color="#FF9800")
        ax.bar(x + width, nl_vals, width, label="Natural Language", color="#4CAF50")

        ax.set_ylabel("Characters")
        ax.set_title("Token Efficiency: SAG vs JSON vs Natural Language")
        ax.set_xticks(x)
        ax.set_xticklabels(names, rotation=45, ha="right")
        ax.legend()
        plt.tight_layout()

        chart_path = os.path.join(reports_dir, "token_efficiency.png")
        plt.savefig(chart_path, dpi=150)
        print(f"Chart saved to {chart_path}")
    except ImportError:
        print("matplotlib not available, skipping chart generation")


if __name__ == "__main__":
    run()
