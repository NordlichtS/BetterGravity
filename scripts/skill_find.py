#!/usr/bin/env python3
"""Zero-bloat local BM25 + 2-level tree router for Antigravity skills."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Ensure sibling import works regardless of caller CWD.
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_skill_index  # noqa: E402


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if callable(reconfig):
            reconfig(encoding="utf-8", errors="replace")


def _load_index() -> dict[str, Any]:
    current_fp = build_skill_index.compute_source_fingerprint()
    data: dict[str, Any] | None = None
    if build_skill_index.INDEX_PATH.exists():
        try:
            parsed = json.loads(build_skill_index.INDEX_PATH.read_text(encoding="utf-8"))
            if (
                isinstance(parsed, dict)
                and parsed.get("version") == build_skill_index.INDEX_VERSION
                and parsed.get("fingerprint") == current_fp
            ):
                data = parsed
        except (OSError, json.JSONDecodeError):
            data = None

    if data is None:
        info = build_skill_index.build()
        print(
            f"[skill-router] auto-rebuilt index: {info['unique_skills']} skills / {info['domains']} domains",
            file=sys.stderr,
        )
        data = json.loads(build_skill_index.INDEX_PATH.read_text(encoding="utf-8"))
    return data


def _get_plugin_enabled_map() -> dict[str, bool]:
    cfg_path = build_skill_index.CONFIG_DIR / "config.json"
    if not cfg_path.exists():
        return {}
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    plugins = cfg.get("plugins")
    if not isinstance(plugins, dict):
        return {}
    result: dict[str, bool] = {}
    for name, meta in plugins.items():
        if isinstance(meta, dict):
            result[name] = bool(meta.get("enabled", True))
        else:
            result[name] = True
    return result


def _expand_query(
    query: str, synonyms: dict[str, str]
) -> tuple[Counter[str], list[str], list[str]]:
    """Build weighted query token counts plus (orig_ascii, expanded_ascii) terms."""
    q_weights: Counter[str] = Counter()

    raw_tokens = build_skill_index.tokenize_text(query, include_cn_bigrams=True)
    for tok in raw_tokens:
        q_weights[tok] += 2

    # Expand Chinese phrases longest-first and mask matched spans so shorter
    # substrings (e.g. Google Cloud inside Google Drive) do not falsely re-trigger.
    remaining = query
    matched_en: list[str] = []
    for cn_key in sorted(synonyms, key=len, reverse=True):
        if cn_key in remaining:
            matched_en.append(synonyms[cn_key])
            remaining = remaining.replace(cn_key, " ")

    expanded_tokens = build_skill_index.tokenize_text(" ".join(matched_en), include_cn_bigrams=False)
    for tok in expanded_tokens:
        if tok not in q_weights:
            q_weights[tok] = 1

    orig_ascii = build_skill_index.tokenize_text(query, include_cn_bigrams=False)
    return q_weights, sorted(set(orig_ascii)), sorted(set(expanded_tokens) - set(orig_ascii))


def _score_skill(
    idx: int,
    skill: dict[str, Any],
    bm25: dict[str, Any],
    q_weights: Counter[str],
    orig_ascii: list[str],
    expanded_ascii: list[str],
) -> float:
    tf_map: dict[str, int] = bm25["doc_tf"][idx]
    dl = bm25["doc_lens"][idx]
    avg_dl = bm25["avg_dl"] or 1.0
    k1 = bm25["k1"]
    b = bm25["b"]
    idf_map: dict[str, float] = bm25["idf"]

    score = 0.0
    for tok, qw in q_weights.items():
        tf = tf_map.get(tok, 0)
        if tf <= 0:
            continue
        idf = idf_map.get(tok, 0.0)
        denom = tf + k1 * (1.0 - b + b * (dl / avg_dl))
        score += qw * idf * ((tf * (k1 + 1.0)) / denom)

    if score <= 0.0:
        return 0.0

    # Extra precision boost for exact/part match on skill name; prioritize explicit terms.
    skill_name = skill["name"].lower()
    name_parts = set(skill_name.split("-"))
    for term in orig_ascii:
        if len(term) < 2:
            continue
        if term == skill_name:
            score += 15.0
        elif term in name_parts:
            score += 8.0
        elif term in skill_name:
            score += 4.0

    for term in expanded_ascii:
        if len(term) < 2:
            continue
        if term == skill_name:
            score += 6.0
        elif term in name_parts:
            score += 2.0

    return score


def cmd_search(args: argparse.Namespace) -> int:
    data = _load_index()
    enabled_map = _get_plugin_enabled_map()
    query = " ".join(args.query).strip()
    if not query:
        print("Empty query. Run `tree` to browse domains.")
        return 1

    q_weights, orig_ascii, expanded_ascii = _expand_query(query, data.get("synonyms", {}))
    bm25 = data["bm25"]
    skills = data["skills"]
    domain_filter = (args.domain or "").strip().lower()

    scored: list[tuple[float, dict[str, Any]]] = []
    for idx, sk in enumerate(skills):
        if domain_filter and not sk["domain"].lower().startswith(domain_filter):
            continue
        sc = _score_skill(idx, sk, bm25, q_weights, orig_ascii, expanded_ascii)
        if sc > 0.0:
            scored.append((sc, sk))

    scored.sort(key=lambda item: (-item[0], item[1]["name"]))
    top_k = max(1, min(args.k, 10))
    results = scored[:top_k]

    if not results:
        print(f"Query: {query} (0 matches)")
        print("Hint: run `tree` to list domains, or retry with broader keywords.")
        return 0

    print(f"Query: {query} (matched {len(scored)} skills, showing top {len(results)})")
    for rank, (sc, sk) in enumerate(results, start=1):
        plugin = sk.get("plugin")
        if plugin:
            status = "enabled" if enabled_map.get(plugin, True) else "disabled"
            print(
                f"[{rank}] {sk['name']} | {sk['domain']} | plugin: {plugin} ({status}) "
                f"| mode: {sk['mode']} | score: {sc:.2f}"
            )
            print(f"    {sk['one_liner']}")
            print(f"    SKILL: {sk['path']}")
            if status == "disabled":
                if sk["mode"] == "direct":
                    print(
                        f"    Plugin (disabled, optional): [{plugin}](customization://{plugin})  "
                        f"OR  agy plugin enable {plugin}"
                    )
                else:
                    print(
                        f"    Enable required: [{plugin}](customization://{plugin})  "
                        f"OR  agy plugin enable {plugin}"
                    )
        else:
            print(
                f"[{rank}] {sk['name']} | {sk['domain']} | source: local-skill "
                f"| mode: direct | score: {sc:.2f}"
            )
            print(f"    {sk['one_liner']}")
            print(f"    SKILL: {sk['path']}")
    return 0


def cmd_tree(args: argparse.Namespace) -> int:
    data = _load_index()
    enabled_map = _get_plugin_enabled_map()
    domain_prefix = (args.domain or "").strip().lower()
    if not domain_prefix:
        for dom in data["domains"]:
            print(f"{dom['id']} ({dom['count']} skills) - {dom['title']}")
        return 0

    matched = [
        sk for sk in data["skills"] if sk["domain"].lower().startswith(domain_prefix)
    ]
    if not matched:
        print(f"No domain matching `{args.domain}`. Run `tree` without arguments to list domains.")
        return 0

    for sk in matched:
        summary = sk["one_liner"]
        if len(summary) > 90:
            summary = summary[:89].rstrip() + "..."
        plugin = sk.get("plugin")
        if plugin:
            status = "enabled" if enabled_map.get(plugin, True) else "disabled"
            tag = f"{plugin}:{status} | {sk['mode']}"
        else:
            tag = "local | direct"
        print(f"- {sk['name']} [{tag}]: {summary}")
    return 0


def cmd_rebuild(_args: argparse.Namespace) -> int:
    info = build_skill_index.build()
    print(
        f"Rebuilt {info['unique_skills']} unique skills across {info['domains']} domains "
        f"(fp={info['fingerprint']}) -> {info['index_path']} | {info['tree_path']}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(
        prog="skill_find.py",
        description="Local CPU BM25 + 2-level tree lookup for Antigravity skills.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_search = sub.add_parser("search", help="BM25 search across local skill index")
    p_search.add_argument("query", nargs="+", help="Search keywords (CN or EN)")
    p_search.add_argument("-k", type=int, default=3, help="Max results (default: 3)")
    p_search.add_argument("--domain", default="", help="Optional domain prefix filter")
    p_search.set_defaults(func=cmd_search)

    p_tree = sub.add_parser("tree", help="Show Level-1/2 domain tree or skills in one domain")
    p_tree.add_argument("domain", nargs="?", default="", help="Optional domain prefix")
    p_tree.set_defaults(func=cmd_tree)

    p_rebuild = sub.add_parser("rebuild", help="Rebuild index.json and TREE.md from disk")
    p_rebuild.set_defaults(func=cmd_rebuild)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
