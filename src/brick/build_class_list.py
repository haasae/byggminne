"""Extract the official Brick class list from a downloaded Brick.ttl.

Keeps "never invent" honest at the ontology level: tests assert every class in
knowledge_base/brick_mapping.json exists in the committed class list, so a
typo'd or hallucinated class name fails the suite. The ~15 MB Brick.ttl itself
is NOT committed -- only the derived class list + provenance.

    # one-time: download https://brickschema.org/schema/1.4/Brick.ttl, then
    python -m src.brick.build_class_list --brick-ttl <path/to/Brick.ttl> \
        --release 1.4 --source-url https://brickschema.org/schema/1.4/Brick.ttl
"""
import argparse
import json
from datetime import date
from pathlib import Path

from rdflib import Graph, RDF, RDFS, URIRef

from src.brick.mapping import BRICK
from src.common.io_utils import configure_stdout_utf8, repo_root

CLASS_LIST_FILE = "knowledge_base/brick_dir/brick_classes.txt"
META_FILE = "knowledge_base/brick_dir/brick_meta.json"
OWL_CLASS = URIRef("http://www.w3.org/2002/07/owl#Class")


def extract_classes(ttl_path):
    """Sorted local names of every owl:Class/rdfs:Class in the Brick namespace."""
    g = Graph()
    g.parse(str(ttl_path), format="turtle")
    names = set()
    for cls_type in (OWL_CLASS, RDFS.Class):
        for subject in g.subjects(RDF.type, cls_type):
            iri = str(subject)
            if iri.startswith(BRICK):
                names.add(iri[len(BRICK):])
    return sorted(names)


def main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(
        description="Derive knowledge_base/brick_dir/brick_classes.txt from Brick.ttl."
    )
    ap.add_argument("--brick-ttl", required=True, help="downloaded Brick.ttl")
    ap.add_argument("--release", required=True, help="Brick release tag, e.g. 1.4")
    ap.add_argument("--source-url", required=True)
    args = ap.parse_args()

    names = extract_classes(args.brick_ttl)
    if not names:
        raise SystemExit("no Brick classes found -- wrong file or namespace?")

    out = repo_root() / CLASS_LIST_FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(names) + "\n", encoding="utf-8")
    meta = {
        "release": args.release,
        "source_url": args.source_url,
        "retrieved": date.today().isoformat(),
        "n_classes": len(names),
        "generator": "python -m src.brick.build_class_list",
    }
    (repo_root() / META_FILE).write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"{len(names)} Brick classes -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
