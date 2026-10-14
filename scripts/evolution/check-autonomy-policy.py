#!/usr/bin/env python3
"""What does the live autonomy policy actually say about the actions that matter?

Read-only, static (no app import, no DB). Prints, for a named list of consequential actions:
the resolved default level, the ceiling, the policy bucket, and the reason.

This is the check that decides whether the fail-closed gate is real or is a row that
happens to exist. A matrix that gives every dispatcher name a row is not a safety system
if that row says `default: 4`.
"""
from __future__ import annotations

import ast
import json
import os
import sys

ROOT = os.environ.get("COMPANY_ROOT", "/opt/company")
GEN = os.path.join(ROOT, "app/services/autonomy_matrix_generated.py")
CUR = os.path.join(ROOT, "app/services/autonomy.py")

CONSEQUENTIAL = [
    # people / staff
    "hire_department", "fire_agent", "reactivate_agent", "send_directive",
    "propose_mission", "update_mission", "delete_tool", "schedule_action",
    # outbound comms
    "gmail_send", "dialpad_send_sms", "gv_send_sms", "send_sms", "send_email",
    # money
    "record_payment", "create_invoice", "stripe_charge", "issue_refund",
    "create_work_order", "create_customer", "contact_update", "calendar_delete",
    # system
    "run_command", "code_self_edit", "apply_patch", "restart_service",
    "write_file", "delete_file",
    # business families
    "shop_create_order", "website_publish", "website_deploy",
    "deep_research", "ask_advisor",
]


def load_dict(path: str, name: str):
    tree = ast.parse(open(path).read())
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            try:
                return ast.literal_eval(node.value)
            except Exception:
                return None
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    try:
                        return ast.literal_eval(node.value)
                    except Exception:
                        return None
    return None


def main() -> int:
    gen = load_dict(GEN, "GENERATED_MATRIX") or {}
    unclassified = load_dict(CUR, "UNCLASSIFIED_ACTION_LEVEL")
    reasons = load_dict(GEN, "POLICY_REASONS") or {}
    restricted = load_dict(GEN, "RESTRICTED_ACTION_LEVELS") or {}

    print(f"GENERATED_MATRIX rows: {len(gen)}")
    print(f"UNCLASSIFIED_ACTION_LEVEL: {unclassified}")
    print(f"RESTRICTED_ACTION_LEVELS: {len(restricted)}")
    print()

    from collections import Counter
    dist = Counter(r.get("default") for r in gen.values() if isinstance(r, dict))
    print(f"default-level distribution: {dict(sorted(dist.items()))}")
    print()

    print("### the actions that matter")
    print(f"{'action':32} {'default':>7} {'max':>4} {'policy':22} reason")
    print("-" * 130)
    missing = []
    for a in CONSEQUENTIAL:
        r = gen.get(a)
        if r is None:
            missing.append(a)
            print(f"{a:32} {'ABSENT':>7} {'-':>4} {'-':22} not in GENERATED_MATRIX -> resolves to {unclassified}")
            continue
        print(f"{a:32} {str(r.get('default')):>7} {str(r.get('max')):>4} {str(r.get('policy')):22} {str(r.get('reason',''))[:70]}")

    print()
    print(f"ABSENT from the generated matrix: {len(missing)} -> {missing}")

    # The real question: which names in the matrix still execute with no human?
    l4 = sorted(a for a, r in gen.items() if isinstance(r, dict) and r.get("default") == 4)
    print()
    print(f"names that still execute with NO human (default 4): {len(l4)}")
    print(", ".join(l4))
    return 0


if __name__ == "__main__":
    sys.exit(main())
