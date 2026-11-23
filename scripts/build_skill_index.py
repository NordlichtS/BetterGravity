#!/usr/bin/env python3
"""Build a local 2-level domain tree and BM25 index for Antigravity skills.

Scans plugin skills (~/.gemini/config/plugins/*/skills/**/SKILL.md) and loose
user skills (~/.agents/skills/*/SKILL.md) and writes compact index.json + TREE.md
to ~/.gemini/config/plugins/budget-orchestrator/skill-index/ without keeping
catalogs in LLM context.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

HOME_DIR = Path.home()
CONFIG_DIR = HOME_DIR / ".gemini" / "config"
PLUGINS_DIR = CONFIG_DIR / "plugins"
USER_SKILLS_DIR = HOME_DIR / ".agents" / "skills"
INDEX_DIR = PLUGINS_DIR / "budget-orchestrator" / "skill-index"
INDEX_PATH = INDEX_DIR / "index.json"
TREE_PATH = INDEX_DIR / "TREE.md"
INDEX_VERSION = 2

USER_SOURCE_KEY = "__user_skills__"

# (domain_id, domain_title_en, domain_keywords)
DOMAIN_MAP: dict[str, tuple[str, str, str]] = {
    "scientific-literature": (
        "science/literature",
        "Academic Literature, Clinical Trials & FDA",
        "paper literature review preprint journal academic citation",
    ),
    "chemistry": (
        "science/chemistry",
        "Chemistry, Cheminformatics & RDKit",
        "chemistry cheminformatics molecule compound medicinal ligand",
    ),
    "genomics": (
        "science/genomics",
        "Genomics, Variants & Regulation",
        "genomics gene variant mutation locus regulatory",
    ),
    "structural-biology": (
        "science/structural-biology",
        "Structural Biology & Proteins",
        "structural biology protein biomolecular sequence 3d",
    ),
    "science-overview": (
        "science/overview",
        "Science Plugins Overview",
        "science overview plugins highlights",
    ),
    "data-agent-kit-plugin": (
        "cloud-data/gcp-dak",
        "Google Cloud Data Engineering (BigQuery, Spark, Airflow, Databases)",
        "gcp google cloud data engineering database pipeline",
    ),
    "chrome-devtools-plugin": (
        "web/devtools",
        "Chrome DevTools Debugging, Performance & A11y",
        "chrome devtools browser web debugging performance",
    ),
    "modern-web-guidance-plugin": (
        "web/modern-web",
        "Modern Web APIs & Chrome Extensions",
        "web frontend html css javascript dom browser",
    ),
    "android-cli-plugin": (
        "platforms/android",
        "Android CLI, Emulators & Compose Preview",
        "android mobile emulator device ui",
    ),
    "gemini-api": (
        "platforms/gemini-api",
        "Gemini API, Live API & Omni Video SDK",
        "gemini api genai sdk multimodal",
    ),
    "google_maps_platform": (
        "platforms/maps",
        "Google Maps Platform APIs",
        "google maps location geo navigation",
    ),
    "google-antigravity-sdk": (
        "platforms/antigravity-sdk",
        "Google Antigravity Python SDK",
        "antigravity agy sdk multi-agent",
    ),
    "gdrive": (
        "productivity/gdrive",
        "Google Drive File Management",
        "google drive cloud storage file folder",
    ),
    USER_SOURCE_KEY: (
        "local/custom",
        "Local User Skills (~/.agents/skills)",
        "local custom workstation skill",
    ),
}

# Preferred plugin when the same skill name appears in multiple plugins.
DEDUP_PREFERENCE: dict[str, str] = {
    "pubmed-database": "scientific-literature",
    "literature-search-openalex": "scientific-literature",
    "credentials": "chemistry",
    "uv": "chemistry",
    "workflow-skill-creator": "chemistry",
}

# Curated CN -> EN query expansion map used at search time only (not emitted to stdout).
CN_EN_SYNONYMS: dict[str, str] = {
    "科学阅读": "scientific literature paper arxiv openalex pubmed",
    "学术论文": "paper literature arxiv biorxiv europepmc openalex pubmed",
    "科研": "scientific research paper literature arxiv openalex pubmed",
    "论文": "paper literature arxiv biorxiv europepmc openalex pubmed",
    "文献": "literature paper pubmed europepmc openalex arxiv biorxiv",
    "综述": "literature review paper pubmed openalex europepmc",
    "预印本": "preprint arxiv biorxiv medrxiv",
    "期刊": "journal openalex europepmc pubmed",
    "学术": "academic paper literature openalex arxiv pubmed",
    "科学": "science scientific literature overview",
    "临床试验": "clinical trials nct clinicaltrials",
    "临床": "clinical trials pubmed clinvar",
    "药监": "fda openfda drug adverse recall",
    "药品": "drug openfda chembl pubchem",
    "铭文": "epigraphy ancient inscription predictingthepast",
    "古文字": "ancient text epigraphy predictingthepast",
    "化学": "chemistry cheminformatics rdkit pubchem chembl",
    "分子": "molecule ligand cheminformatics rdkit pubchem",
    "化合物": "compound molecule pubchem chembl rdkit",
    "药物": "drug chembl pubchem cofolding docking admet",
    "药化": "medicinal chemistry sar qsar mmpa rdkit",
    "反应": "reaction retrosynthesis synthesis smarts",
    "逆合成": "retrosynthesis reaction synthesis route",
    "对接": "docking vina smina 3d physics",
    "分子动力学": "molecular dynamics openmm conformer physics",
    "构象": "conformer dihedral torsion strain physics",
    "专利": "patent doc2mol opsin markush",
    "基因组": "genomics gnomad ensembl ucsc encode",
    "基因": "gene ensembl gtex quickgo opentargets",
    "变异": "variant clinvar gnomad dbsnp alphagenome vep",
    "突变": "mutation variant clinvar gnomad vep",
    "位点": "locus rsid dbsnp clinvar alphagenome",
    "致病性": "pathogenicity clinvar alphagenome",
    "表达": "expression rna gtex hpa alphagenome",
    "转录因子": "transcription factor tfbs jaspar unibind ucsc",
    "保守性": "conservation phylop phastcons ucsc",
    "调控": "regulatory enhancer promoter encode ccre alphagenome",
    "蛋白质": "protein uniprot pdb alphafold interpro string",
    "蛋白": "protein uniprot pdb alphafold interpro string",
    "结构": "structure 3d pdb mmcif alphafold foldseek pymol viewer",
    "折叠": "folding alphafold cofolding boltz",
    "三维": "3d structure viewer pdb alphafold foldseek pymol",
    "序列": "sequence ncbi uniprot msa similarity search",
    "比对": "alignment msa clustal mmseqs2 blast pymol",
    "同源": "homologue similarity mmseqs2 blast",
    "互作": "interaction ppi string",
    "通路": "pathway reactome quickgo",
    "域": "domain family pfam interpro",
    "谷歌云": "gcp google cloud bigquery gcs spark composer",
    "数仓": "bigquery data warehouse sql optimization",
    "数据仓库": "bigquery data warehouse",
    "大数据": "bigquery spark dataproc dataflow",
    "管道": "pipeline dataform dbt airflow composer dataflow",
    "调度": "airflow composer dag orchestration",
    "数据库": "database bigquery spanner bigtable alloydb cloudsql firestore",
    "存储桶": "gcs bucket cloud storage",
    "湖仓": "lakehouse iceberg federate catalog",
    "机器学习": "ml bigframes ai forecasting regression classification",
    "清洗": "autocleaning data quality transformation",
    "成本": "cost optimization billing capacity",
    "优化": "optimization optimize performance cost",
    "排障": "troubleshooting rca debug failure",
    "故障": "troubleshooting failure error rca",
    "慢查询": "troubleshooting slow query execution graph",
    "网页": "web html css devtools chrome lcp",
    "前端": "web frontend html css modern web",
    "性能": "performance lcp cwv devtools",
    "内存泄漏": "memory leak heap snapshot devtools",
    "内存": "memory leak heap devtools",
    "无障碍": "accessibility a11y aria contrast devtools",
    "浏览器": "browser chrome devtools",
    "扩展": "chrome extension manifest v3",
    "弹窗": "modal dialog popover modern web",
    "表单": "forms validation autofill modern web",
    "暗黑模式": "dark mode modern web",
    "安卓": "android cli adb avd device hub compose",
    "手机": "android device hub adb mirror",
    "模拟器": "emulator avd android device hub",
    "预览": "compose preview android",
    "界面": "ui layout compose preview",
    "多模态": "gemini api multimodal live omni",
    "语音": "tts speech live audio gemini api",
    "实时": "live websocket streaming gemini api",
    "视频": "video omni flash gemini api",
    "接口": "api sdk gemini",
    "模型": "model gemini ml",
    "地图": "google maps places routing",
    "导航": "routing eta google maps",
    "地理": "geocoding places google maps",
    "路线": "routing google maps",
    "谷歌云盘": "gdrive google drive",
    "云盘": "gdrive google drive",
    "网盘": "gdrive google drive",
    "谷歌文档": "gdrive google drive",
    "智能体": "agent subagent antigravity sdk dsh",
    "着色器": "hlsl shader directx fx fxc",
    "图形": "hlsl shader directx",
    "渲染": "hlsl shader directx",
    "深度求索": "deepseek dsh subagent",
}

FIELD_WEIGHTS: dict[str, float] = {
    "name": 3.5,
    "domain": 2.0,
    "tags": 2.0,
    "description": 1.0,
}


def tokenize_text(text: str, include_cn_bigrams: bool = True) -> list[str]:
    """Tokenize ASCII identifiers and optional Chinese character unigrams/bigrams."""
    if not text:
        return []
    lowered = text.lower()
    tokens: list[str] = []

    for raw in re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", lowered):
        tokens.append(raw)
        if "-" in raw or "_" in raw:
            parts = [p for p in re.split(r"[-_]+", raw) if p]
            if len(parts) > 1:
                tokens.extend(parts)

    if include_cn_bigrams:
        for seq in re.findall(r"[\u4e00-\u9fff]+", text):
            if len(seq) == 1:
                tokens.append(seq)
            else:
                for i in range(len(seq) - 1):
                    tokens.append(seq[i : i + 2])
    return tokens


def _strip_quotes(val: str) -> str:
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        inner = val[1:-1]
        if val[0] == "'":
            inner = inner.replace("''", "'")
        return inner.strip()
    return val


def parse_frontmatter(skill_md: Path) -> tuple[str, str]:
    """Extract (name, description) from a SKILL.md YAML frontmatter block."""
    raw = skill_md.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        return skill_md.parent.name, ""

    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        return skill_md.parent.name, ""

    fm_lines = lines[1:end_idx]
    parsed: dict[str, str] = {}
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key = m.group(1)
        val = m.group(2).strip()
        if val in (">", ">-", "|", "|-"):
            block_lines: list[str] = []
            j = i + 1
            while j < len(fm_lines):
                nxt = fm_lines[j]
                if nxt.strip() == "":
                    block_lines.append("")
                    j += 1
                elif nxt.startswith((" ", "\t")):
                    block_lines.append(nxt.strip())
                    j += 1
                else:
                    break
            if val.startswith("|"):
                parsed[key] = "\n".join(block_lines).strip()
            else:
                parsed[key] = " ".join(part for part in block_lines if part).strip()
            i = j
        else:
            cont_lines = [val] if val else []
            j = i + 1
            while j < len(fm_lines):
                nxt = fm_lines[j]
                if nxt.startswith((" ", "\t")) and not re.match(r"^\s+[A-Za-z0-9_-]+:\s*", nxt):
                    if nxt.strip():
                        cont_lines.append(nxt.strip())
                    j += 1
                elif nxt.strip() == "" and j + 1 < len(fm_lines) and fm_lines[j + 1].startswith((" ", "\t")):
                    j += 1
                else:
                    break
            joined = " ".join(p for p in cont_lines if p).strip()
            parsed[key] = _strip_quotes(joined)
            i = j

    name = parsed.get("name") or skill_md.parent.name
    desc = re.sub(r"\s+", " ", parsed.get("description", "")).strip()
    return name, desc


def make_one_liner(desc: str, max_len: int = 140) -> str:
    """Create a concise single-line summary from a skill description."""
    clean = re.sub(r"\s+", " ", desc).strip()
    if not clean:
        return "(no description)"
    if len(clean) <= max_len:
        return clean
    for m in re.finditer(r"\.\s+", clean):
        end = m.start() + 1
        if 45 <= end <= max_len:
            return clean[:end]
    cut = clean[: max_len - 1].rsplit(" ", 1)[0]
    if len(cut) < max_len // 2:
        cut = clean[: max_len - 1]
    return cut + "..."


def _read_plugin_manifest(plugin_dir: Path | None) -> dict[str, Any]:
    if not plugin_dir:
        return {}
    manifest_path = plugin_dir / "plugin.json"
    if not manifest_path.exists():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def classify_mode(plugin_name: str, skill_name: str, plugin_dir: Path | None) -> str:
    """Classify activation mode for a skill using explicit overrides and manifest checks."""
    if plugin_name == USER_SOURCE_KEY:
        return "direct"
    if plugin_name == "structural-biology":
        return "needs-mcp" if skill_name == "biomolecular-structure-viewer" else "direct"
    if plugin_name == "android-cli-plugin":
        return "needs-sidecar" if skill_name in ("android-device-hub", "compose-preview") else "direct"

    if not plugin_dir:
        return "direct"

    if (plugin_dir / "mcp_config.json").exists() or (plugin_dir / ".mcp.json").exists():
        return "needs-mcp"

    sidecars_dir = plugin_dir / "sidecars"
    if sidecars_dir.is_dir():
        norm_skill = re.sub(r"[^a-z0-9]", "", skill_name.lower())
        for sub in sidecars_dir.iterdir():
            if not sub.is_dir():
                continue
            norm_sidecar = re.sub(r"[^a-z0-9]", "", sub.name.lower())
            if norm_sidecar and (norm_sidecar in norm_skill or norm_skill in norm_sidecar):
                return "needs-sidecar"

    manifest = _read_plugin_manifest(plugin_dir)
    ag_ext = manifest.get("extensions", {}).get("com.google.antigravity", {})
    if isinstance(ag_ext, dict) and (ag_ext.get("contextProviders") or ag_ext.get("authProviders")):
        return "needs-plugin"
    if manifest.get("authProviders"):
        return "needs-plugin"

    return "direct"


def domain_for_source(source_key: str, plugin_dir: Path | None = None) -> tuple[str, str, str]:
    """Return (domain_id, domain_title, domain_keywords) for a plugin or user skills."""
    if source_key in DOMAIN_MAP:
        return DOMAIN_MAP[source_key]

    manifest = _read_plugin_manifest(plugin_dir)
    display_name = str(manifest.get("displayName") or source_key).strip()
    desc = str(manifest.get("description") or "").strip()
    raw_kw = manifest.get("keywords") or []
    kw_list = [str(k).strip() for k in raw_kw] if isinstance(raw_kw, list) else []

    title = display_name
    if desc:
        short_desc = make_one_liner(desc, max_len=72)
        title = f"{display_name} - {short_desc}"

    tags = " ".join(
        part
        for part in [source_key.replace("-", " ").replace("_", " "), display_name, *kw_list]
        if part
    )
    return (f"other/{source_key}", title, tags)


def compute_source_fingerprint() -> str:
    """Compute a fast deterministic hash of installed skill files and plugin manifests."""
    records: list[str] = []

    if PLUGINS_DIR.exists():
        for pdir in sorted(PLUGINS_DIR.iterdir()):
            if not pdir.is_dir():
                continue
            skills_root = pdir / "skills"
            if not skills_root.exists():
                continue
            has_pj = int((pdir / "plugin.json").exists())
            has_mcp = int((pdir / "mcp_config.json").exists() or (pdir / ".mcp.json").exists())
            sidecars_dir = pdir / "sidecars"
            sidecar_names = (
                ",".join(sorted(x.name for x in sidecars_dir.iterdir() if x.is_dir()))
                if sidecars_dir.is_dir()
                else ""
            )
            records.append(f"plugin:{pdir.name}:pj={has_pj}:mcp={has_mcp}:sc={sidecar_names}")
            for sf in sorted(skills_root.rglob("SKILL.md")):
                try:
                    st = sf.stat()
                    records.append(f"skill:{sf.resolve().as_posix()}:{st.st_mtime_ns}:{st.st_size}")
                except OSError:
                    continue

    if USER_SKILLS_DIR.exists():
        for sf in sorted(USER_SKILLS_DIR.glob("*/SKILL.md")):
            try:
                st = sf.stat()
                records.append(f"user:{sf.resolve().as_posix()}:{st.st_mtime_ns}:{st.st_size}")
            except OSError:
                continue

    digest = hashlib.sha256("\n".join(sorted(records)).encode("utf-8")).hexdigest()
    return digest[:16]


def _discover_raw_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    if PLUGINS_DIR.exists():
        for pdir in sorted(PLUGINS_DIR.iterdir()):
            if not pdir.is_dir():
                continue
            plugin_name = pdir.name
            skills_root = pdir / "skills"
            if not skills_root.exists():
                continue
            skill_files = sorted(skills_root.rglob("SKILL.md"))
            dom_id, dom_title, dom_kw = domain_for_source(plugin_name, pdir)
            for sf in skill_files:
                name, desc = parse_frontmatter(sf)
                entries.append(
                    {
                        "name": name,
                        "source": plugin_name,
                        "plugin": plugin_name,
                        "domain": dom_id,
                        "domain_title": dom_title,
                        "tags": dom_kw,
                        "description": desc,
                        "one_liner": make_one_liner(desc),
                        "mode": classify_mode(plugin_name, name, pdir),
                        "path": str(sf.resolve()),
                    }
                )

    if USER_SKILLS_DIR.exists():
        dom_id, dom_title, dom_kw = domain_for_source(USER_SOURCE_KEY)
        for sf in sorted(USER_SKILLS_DIR.glob("*/SKILL.md")):
            name, desc = parse_frontmatter(sf)
            entries.append(
                {
                    "name": name,
                    "source": USER_SOURCE_KEY,
                    "plugin": None,
                    "domain": dom_id,
                    "domain_title": dom_title,
                    "tags": dom_kw,
                    "description": desc,
                    "one_liner": make_one_liner(desc),
                    "mode": "direct",
                    "path": str(sf.resolve()),
                }
            )

    return entries


def _deduplicate_entries(raw_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in raw_entries:
        grouped.setdefault(item["name"], []).append(item)

    deduped: list[dict[str, Any]] = []
    for name in sorted(grouped):
        candidates = grouped[name]
        preferred_source = DEDUP_PREFERENCE.get(name)
        winner = candidates[0]
        if preferred_source:
            for c in candidates:
                if c["source"] == preferred_source:
                    winner = c
                    break

        others = [
            c["plugin"]
            for c in candidates
            if c is not winner and c["plugin"] and c["plugin"] != winner["plugin"]
        ]
        winner_copy = dict(winner)
        winner_copy["also_in_plugins"] = sorted(set(others))
        deduped.append(winner_copy)

    deduped.sort(key=lambda x: (x["domain"], x["name"]))
    return deduped


def _compute_bm25_stats(skills: list[dict[str, Any]]) -> dict[str, Any]:
    doc_tf: list[dict[str, int]] = []
    doc_lens: list[int] = []
    df: Counter[str] = Counter()

    for sk in skills:
        tf_counter: Counter[str] = Counter()
        weighted_sources = [
            (sk["name"], FIELD_WEIGHTS["name"]),
            (f"{sk['domain']} {sk['domain_title']} {sk['plugin'] or ''}", FIELD_WEIGHTS["domain"]),
            (sk["tags"], FIELD_WEIGHTS["tags"]),
            (sk["description"], FIELD_WEIGHTS["description"]),
        ]
        for text, weight in weighted_sources:
            rep = max(1, round(weight * 2))
            for tok in tokenize_text(text, include_cn_bigrams=True):
                tf_counter[tok] += rep

        doc_len = sum(tf_counter.values())
        doc_tf.append(dict(tf_counter))
        doc_lens.append(doc_len)
        for tok in tf_counter:
            df[tok] += 1

    n_docs = len(skills)
    avg_dl = (sum(doc_lens) / n_docs) if n_docs else 1.0
    idf = {
        tok: math.log(1.0 + (n_docs - freq + 0.5) / (freq + 0.5))
        for tok, freq in df.items()
    }
    return {
        "k1": 1.5,
        "b": 0.65,
        "n_docs": n_docs,
        "avg_dl": avg_dl,
        "idf": idf,
        "doc_lens": doc_lens,
        "doc_tf": doc_tf,
    }


def _render_tree_md(domains: list[dict[str, Any]], skills: list[dict[str, Any]]) -> str:
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for sk in skills:
        by_domain.setdefault(sk["domain"], []).append(sk)

    lines = [
        "# Antigravity Offline Skill Tree",
        "",
        f"> Generated: {_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
        f"Domains: {len(domains)} | Unique Skills: {len(skills)}",
        "> Offline catalog for local CPU lookup (`skill_find.py`). Do NOT inject into prompts.",
        "",
        "## Level 1 / Level 2 Domains",
        "",
    ]
    for dom in domains:
        lines.append(f"- `{dom['id']}` ({dom['count']} skills) - {dom['title']}")
    lines.append("")

    for dom in domains:
        dom_skills = by_domain.get(dom["id"], [])
        lines.append(f"## `{dom['id']}` - {dom['title']} ({len(dom_skills)})")
        lines.append("")
        for sk in dom_skills:
            plugin_tag = f"plugin: `{sk['plugin']}`" if sk["plugin"] else "source: `~/.agents/skills`"
            extra = (
                f" | also in: {', '.join(sk['also_in_plugins'])}"
                if sk.get("also_in_plugins")
                else ""
            )
            lines.append(
                f"- **{sk['name']}** [`{sk['mode']}`] ({plugin_tag}{extra}) - {sk['one_liner']}"
            )
            lines.append(f"  - `SKILL`: `{sk['path']}`")
        lines.append("")

    return "\n".join(lines)


def build() -> dict[str, Any]:
    """Scan local skills, build BM25 index + TREE.md, and return summary metadata."""
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    fingerprint = compute_source_fingerprint()
    raw_entries = _discover_raw_entries()
    skills = _deduplicate_entries(raw_entries)

    domain_counts: Counter[str] = Counter(sk["domain"] for sk in skills)
    domain_titles: dict[str, str] = {sk["domain"]: sk["domain_title"] for sk in skills}
    domains = [
        {
            "id": dom_id,
            "title": domain_titles[dom_id],
            "count": domain_counts[dom_id],
        }
        for dom_id in sorted(domain_counts)
    ]

    bm25 = _compute_bm25_stats(skills)
    payload = {
        "version": INDEX_VERSION,
        "fingerprint": fingerprint,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "raw_skill_count": len(raw_entries),
        "unique_skill_count": len(skills),
        "domains": domains,
        "synonyms": CN_EN_SYNONYMS,
        "skills": [
            {
                "name": sk["name"],
                "domain": sk["domain"],
                "domain_title": sk["domain_title"],
                "plugin": sk["plugin"],
                "also_in_plugins": sk["also_in_plugins"],
                "mode": sk["mode"],
                "one_liner": sk["one_liner"],
                "path": sk["path"],
            }
            for sk in skills
        ],
        "bm25": bm25,
    }

    INDEX_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    TREE_PATH.write_text(_render_tree_md(domains, skills), encoding="utf-8")

    return {
        "domains": len(domains),
        "raw_skills": len(raw_entries),
        "unique_skills": len(skills),
        "fingerprint": fingerprint,
        "index_path": str(INDEX_PATH),
        "tree_path": str(TREE_PATH),
    }


if __name__ == "__main__":
    info = build()
    print(
        f"Built skill index v{INDEX_VERSION}: {info['unique_skills']} unique skills "
        f"(from {info['raw_skills']} entries) across {info['domains']} domains.\n"
        f"Index: {info['index_path']}\n"
        f"Tree:  {info['tree_path']}"
    )
