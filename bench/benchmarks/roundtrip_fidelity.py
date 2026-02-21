#!/usr/bin/env python3
"""Measure fold -> unfold -> diff fidelity."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "python-sag", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sag.parser import SAGMessageParser
from sag.minifier import MessageMinifier
from sag.fold import FoldEngine
from fixtures.conversations import CONVERSATIONS


def run():
    print("=" * 80)
    print("ROUNDTRIP FIDELITY BENCHMARK: Fold -> Unfold -> Diff")
    print("=" * 80)
    print()

    engine = FoldEngine()
    total_messages = 0
    total_perfect = 0

    for conv in CONVERSATIONS:
        name = conv["name"]
        parsed = [SAGMessageParser.parse(m) for m in conv["sag"]]

        # Fold all messages
        fold_stmt = engine.fold(parsed, f"Summary of {name}")

        # Unfold
        unfolded = engine.unfold(fold_stmt.fold_id)

        if unfolded is None:
            print(f"  FAIL: {name} - unfold returned None")
            continue

        # Compare
        perfect = True
        for i, (orig, restored) in enumerate(zip(parsed, unfolded)):
            orig_min = MessageMinifier.to_minified_string(orig)
            restored_min = MessageMinifier.to_minified_string(restored)
            total_messages += 1

            if orig_min == restored_min:
                total_perfect += 1
            else:
                perfect = False
                print(f"  DIFF in {name} message {i}:")
                print(f"    Original: {orig_min[:80]}...")
                print(f"    Restored: {restored_min[:80]}...")

        status = "PERFECT" if perfect else "DIFF"
        print(f"  [{status}] {name}: {len(parsed)} messages")

    print()
    print(f"Total messages: {total_messages}")
    print(f"Perfect roundtrips: {total_perfect}")
    fidelity = total_perfect / total_messages * 100 if total_messages > 0 else 0
    print(f"Fidelity: {fidelity:.1f}%")


if __name__ == "__main__":
    run()
