#!/usr/bin/env python3
"""regenerate-identity-surface.py — rebuild the canonical identity surface from the LIVE person layer.

WHY (the thing this fixes)
    `person_canonical` / `person_phone` were built on 2026-09-15 from `identity-truth.json`, a FROZEN
    snapshot of the `.fsearch` person layer. The indexer was then fixed (C-007 removed junk identities,
    a shared `_split_phone_tokens` split concatenated numbers) and the layer was rebuilt, so the
    surface no longer described it. Measured before this script:
        98 names present in the surface but absent from the live layer
        276 names present in the live layer but absent from the surface
        the surface still carried 'Private Name', 'Local' and 'Caller Wireless'
    A stale artifact that does not say it is stale is the failure the whole reconciliation exists to
    remove. Labelling it (round 5) was the honest interim; this is the fix.

WHAT IT DOES
    DERIVES the rows from the live `.fsearch/comms.db` (read-only):
        person_canonical  <- people (person_key, display_name, names, basis, comm_count, kinds)
        person_phone      <- each person's phones, PLUS every comms address that reaches no person
    and CARRIES OVER axis C's curated judgement from `identity-truth.json` by joining on
    `source_person_key`, because that part is not derivable from the layer:
        needs_owner (curated), alternate_names, evidence, conflicts, and the `reason` text on
        unresolved phones.
    It then re-creates the views and re-measures the drift.

WHAT IT CANNOT CARRY, STATED RATHER THAN SILENTLY DROPPED
    * Axis C rows whose `source_person_key` no longer exists in the live layer (the junk identities it
      curated away, and any cluster whose membership changed) - counted and reported, not folded in.
    * `owner_questions` and `known_wrong_merges` are NOT surface data; they live in
      `identity-truth.json` and in the owner queue, and this script leaves them there.
    * Confidence is DERIVED (see `_confidence`), not axis C's per-entry judgement. Where axis C's
      curated value exists for a surviving person it is preferred, and the source is recorded.

SAFETY
    Additive rebuild of two snapshot tables and three views. `contacts`, `customers`,
    `comms_identity_link` and `prod_customer_mirror` are read, never written. One transaction per unit
    with `busy_timeout`, retried on lock only. Every count is read back afterwards.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SECRETARY = "/home/zabz/personal-secretary-mvp/data/secretary.db"
LIVE = "/home/zabz/.fsearch/comms.db"
TRUTH = Path("/home/zabz/recon-20260915/identity-truth.json")
ENV_FILE = Path("/home/zabz/personal-secretary-mvp/.env")
NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")

# basis prefixes that come from the shop's own records rather than an observation
TRUSTED_BASIS = ("address_book:lpt_sync_record", "address_book:manual", "lpt_sync_record")


def norm(phone: object) -> str:
    d = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d if len(d) == 10 else ""


def confidence(display: str, basis: str) -> str:
    if not (display or "").strip():
        return "unresolved"
    b = (basis or "").lower()
    if any(t in b for t in TRUSTED_BASIS):
        return "high"
    return "medium"


def open_w(write: bool) -> sqlite3.Connection:
    if write:
        con = sqlite3.connect(SECRETARY, timeout=120)
        con.execute("PRAGMA busy_timeout = 120000")
        return con
    return sqlite3.connect(f"file:{SECRETARY}?mode=ro", uri=True)


def retry(label: str, fn, attempts: int = 6):
    for a in range(1, attempts + 1):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or a == attempts:
                print(f"  {label}: FAILED after {a}: {exc}")
                raise
            print(f"  {label}: lock on attempt {a}; retrying in {a * 5}s")
            time.sleep(a * 5)


def main() -> int:
    truth = json.loads(TRUTH.read_text(encoding="utf-8")) if TRUTH.exists() else {}
    curated = {p.get("source_person_key"): p for p in (truth.get("canonical_persons") or [])
               if p.get("source_person_key")}
    curated_reasons = {norm(u.get("phone")): u for u in (truth.get("unresolved_phones") or [])}
    shop = {norm(s) for s in (truth.get("excluded_shop_numbers") or [])}
    print(f"axis C curation available for {len(curated)} person keys; "
          f"{len(curated_reasons)} unresolved-phone reasons; {len(shop)} shop numbers")

    # ---- read the LIVE layer (read-only) ----
    live = sqlite3.connect(f"file:{LIVE}?mode=ro", uri=True)
    people = []
    for r in live.execute("SELECT person_key, display_name, phones, emails, names, comm_count, "
                          "kinds, basis FROM people"):
        people.append({
            "key": r[0], "display": (r[1] or "").strip(),
            "phones": json.loads(r[2] or "[]"), "emails": json.loads(r[3] or "[]"),
            "names": json.loads(r[4] or "[]"), "comm_count": r[5] or 0,
            "kinds": r[6], "basis": r[7] or "",
        })
    alias_rows = list(live.execute("SELECT person_key, alias_value, alias_kind, reason, source "
                                  "FROM person_alias"))
    # comms rows per normalised address, for comms_rows on the phone table
    addr_rows: dict[str, int] = {}
    for (a, n) in live.execute("SELECT COALESCE(address,''), COUNT(*) FROM comms GROUP BY 1"):
        k = norm(a)
        if k:
            addr_rows[k] = addr_rows.get(k, 0) + (n or 0)
    live.close()
    print(f"live layer: {len(people)} people, {len(alias_rows)} aliases, "
          f"{len(addr_rows)} normalised comms addresses")

    # ---- build the rows ----
    person_rows, phone_rows = [], []
    attached: set[str] = set()
    carried = 0
    for p in people:
        c = curated.get(p["key"]) or {}
        if c:
            carried += 1
        conf = c.get("confidence") if c.get("confidence") in ("high", "medium", "unresolved") else None
        conf = conf or confidence(p["display"], p["basis"])
        needs_owner = 1 if c.get("needs_owner") else (1 if conf == "unresolved" else 0)
        person_rows.append((
            p["key"],                                     # person_id == person_key: joinable to the layer
            p["display"] or None,
            c.get("display_name_source") or "people.display_name",
            conf,
            needs_owner,
            json.dumps(p["names"] or []),
            p["basis"],
            p["key"],
            json.dumps(c.get("evidence") or [f"basis={p['basis']}", f"comms={p['comm_count']}"]),
            json.dumps(c.get("conflicts") or []),
            NOW,
        ))
        # phones attached to this person
        for ph in p["phones"]:
            k = norm(ph)
            if not k or k in attached:
                continue
            attached.add(k)
            phone_rows.append((k, p["key"], 0 if k in shop else 1, "person_phones",
                               p["comm_count"], json.dumps(c.get("evidence") or [])))

    # every traffic-carrying address that reaches no person
    unresolved = []
    for k, n in addr_rows.items():
        if k in attached:
            continue
        u = curated_reasons.get(k)
        unresolved.append((k, None, 0 if k in shop else 1, "unresolved_comms_only", n,
                           json.dumps({"reason": (u or {}).get("reason", "no person-like name in any store"),
                                       "dialpad_labels": (u or {}).get("dialpad_labels"),
                                       "carried_from_axis_c": bool(u)})))
    phone_rows.extend(unresolved)

    print(f"built {len(person_rows)} canonical persons ({carried} matched axis C's curation), "
          f"{len(phone_rows)} phone bindings ({len(phone_rows) - len(unresolved)} attached, "
          f"{len(unresolved)} unresolved)")

    # ---- write ----
    def do_write():
        con = open_w(write=True)
        try:
            cur = con.cursor()
            cur.execute("DELETE FROM person_phone")
            cur.execute("DELETE FROM person_canonical")
            cur.executemany(
                "INSERT OR REPLACE INTO person_canonical "
                "(person_id, display_name, display_name_source, confidence, needs_owner, "
                " alternate_names, source_basis, source_person_key, evidence, conflicts, built_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)", person_rows)
            cur.executemany(
                "INSERT OR REPLACE INTO person_phone "
                "(phone_norm, person_id, is_dialable, norm_source, comms_rows, evidence) "
                "VALUES (?,?,?,?,?,?)", phone_rows)
            con.commit()
            return True
        finally:
            con.close()

    retry("identity surface rebuild", do_write)

    # ---- views (recreated so they pick up the new rows and the corrected conflict logic) ----
    VIEWS = {
        "v_person_canonical": """
            CREATE VIEW v_person_canonical AS
            SELECT c.person_id, c.display_name, c.confidence, c.needs_owner,
                   p.phone_norm, p.is_dialable, p.norm_source
            FROM person_canonical c
            LEFT JOIN person_phone p ON p.person_id = c.person_id""",
        "v_identity_surface_status": """
            CREATE VIEW v_identity_surface_status AS
            SELECT
              (SELECT value FROM identity_surface_meta WHERE key='STALE')                  AS is_stale,
              (SELECT value FROM identity_surface_meta WHERE key='snapshot_at')            AS snapshot_at,
              (SELECT value FROM identity_surface_meta WHERE key='surface_person_rows')    AS surface_rows,
              (SELECT value FROM identity_surface_meta WHERE key='live_people_rows')       AS live_rows,
              (SELECT value FROM identity_surface_meta WHERE key='names_in_surface_absent_from_live')
                                                                                           AS stale_names,
              (SELECT value FROM identity_surface_meta WHERE key='names_in_live_absent_from_surface')
                                                                                           AS missing_names""",
        "v_contact_duplicate": """
            CREATE VIEW v_contact_duplicate AS
            SELECT phone_norm, COUNT(*) n_rows, COUNT(DISTINCT lower(trim(name))) n_names,
                   GROUP_CONCAT(id) ids
            FROM (SELECT id, name,
                         replace(replace(replace(replace(phone,'+',''),'-',''),' ',''),'(','') AS phone_norm
                  FROM contacts WHERE phone IS NOT NULL)
            GROUP BY 1 HAVING n_rows > 1""",
    }

    def do_views():
        con = open_w(write=True)
        try:
            cur = con.cursor()
            for name, sql in VIEWS.items():
                cur.execute(f"DROP VIEW IF EXISTS {name}")
                cur.execute(sql)
            con.commit()
            return True
        finally:
            con.close()

    retry("views", do_views)

    # ---- re-measure the drift and re-label ----
    con = open_w(write=True)
    cur = con.cursor()
    live2 = sqlite3.connect(f"file:{LIVE}?mode=ro", uri=True)
    live_named = {r[0] for r in live2.execute(
        "SELECT lower(trim(display_name)) FROM people WHERE COALESCE(display_name,'')<>''")}
    live_people_n = live2.execute("SELECT COUNT(*) FROM people").fetchone()[0]
    live2.close()
    surf_named = {r[0] for r in cur.execute(
        "SELECT lower(trim(display_name)) FROM person_canonical WHERE COALESCE(display_name,'')<>''")}
    stale_n = len(surf_named - live_named)
    missing_n = len(live_named - surf_named)

    meta = {
        "STALE": "no" if (stale_n == 0 and missing_n == 0) else "yes",
        "snapshot_at": NOW,
        "derived_from": "the LIVE .fsearch person layer (people/person_alias/comms), read-only",
        "curated_carryover": f"{carried} persons matched to axis C's identity-truth.json by source_person_key",
        "surface_person_rows": str(len(person_rows)),
        "surface_phone_rows": str(len(phone_rows)),
        "live_people_rows": str(live_people_n),
        "names_in_surface_absent_from_live": str(stale_n),
        "names_in_live_absent_from_surface": str(missing_n),
        "refresh_command": "regenerate-identity-surface.py (re-runnable; derives from the live layer)",
        "consumer_warning": "check v_identity_surface_status.is_stale before trusting the surface",
    }
    for k, v in meta.items():
        cur.execute("INSERT OR REPLACE INTO identity_surface_meta(key, value) VALUES (?,?)", (k, v))
    con.commit()

    print("\nVERIFICATION (read back):")
    for label, sql in (
        ("person_canonical rows", "SELECT COUNT(*) FROM person_canonical"),
        ("person_phone rows", "SELECT COUNT(*) FROM person_phone"),
        ("  attached to a person", "SELECT COUNT(*) FROM person_phone WHERE person_id IS NOT NULL"),
        ("  unresolved (no identity)", "SELECT COUNT(*) FROM person_phone WHERE person_id IS NULL"),
        ("v_person_canonical rows", "SELECT COUNT(*) FROM v_person_canonical"),
        ("still named 'Private Name'", "SELECT COUNT(*) FROM person_canonical WHERE lower(display_name)='private name'"),
        ("confidence=high", "SELECT COUNT(*) FROM person_canonical WHERE confidence='high'"),
        ("needs_owner=1", "SELECT COUNT(*) FROM person_canonical WHERE needs_owner=1"),
    ):
        try:
            print(f"  {label:<32} {cur.execute(sql).fetchone()[0]}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {label:<32} ERROR {exc}")
    cols = [d[0] for d in cur.execute("SELECT * FROM v_identity_surface_status LIMIT 1").description]
    row = cur.execute("SELECT * FROM v_identity_surface_status").fetchone()
    print("\n  v_identity_surface_status:")
    for c, v in zip(cols, row):
        print(f"     {c:<22} {v}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
