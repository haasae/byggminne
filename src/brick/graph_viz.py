"""Render a Brick Turtle graph as a Mermaid diagram inside a Markdown file.

Graphical view of an emitted graph with no new dependency, no network, and no
external tool: Mermaid renders in the VS Code Markdown preview (and GitHub).
rdflib (already a dep) reads the .ttl; nodes are colored by Brick category so a
demo audience sees the typed structure at a glance.

    python -m src.brick.graph_viz runs/<run>/graphs/tasen_20053404.ttl -o graph.md

Pick one *building* graph, not the whole-site .ttl -- 300+ nodes render as a
hairball. Self-check: `python -m src.brick.graph_viz --demo`.
"""
import argparse
from rdflib import Graph, RDF, RDFS

# Brick class local-name -> (category, node fill color). Category drives the
# legend; anything unmapped falls back to the generic "Point" bucket so an
# untyped point reads visually as "not yet classified".
_CATEGORY = {
    "Site": ("site", "#b39ddb"),
    "Building": ("building", "#90caf9"),
}
_SENSOR_FILL = "#a5d6a7"   # any *_Sensor class
_STATUS_FILL = "#ffcc80"   # Status / Alarm / Command
_EQUIP_FILL = "#ef9a9a"    # Pump / AHU / ... (equipment)
_GENERIC_FILL = "#e0e0e0"  # bare brick:Point -- decoded but not typed


def _category(cls):
    if cls in _CATEGORY:
        return _CATEGORY[cls]
    if cls.endswith("_Sensor"):
        return ("sensor", _SENSOR_FILL)
    if cls in ("Status", "Alarm", "Command"):
        return ("status", _STATUS_FILL)
    if cls == "Point":
        return ("point", _GENERIC_FILL)
    return ("equipment", _EQUIP_FILL)  # Pump, AHU, and other equipment classes


def _short(label):
    """Shorten a raw label to its trailing component token for display.

    `...-RT401.#85` -> `RT401`; `...Drenspumpe_P1.-P1_Drift.#85` -> `P1_Drift`.
    Short building/equipment/site labels pass through unchanged.
    """
    parts = [p for p in label.split(".") if p and not p.startswith("#")]
    tail = parts[-1] if parts else label
    return tail.lstrip("-") or label


def _local(uri):
    return str(uri).rsplit("#", 1)[-1]


def render_mermaid(ttl_path):
    g = Graph()
    g.parse(ttl_path, format="turtle")

    labels = {s: str(o) for s, _, o in g.triples((None, RDFS.label, None))}
    classes = {s: _local(o) for s, _, o in g.triples((None, RDF.type, None))}

    lines = ["```mermaid", "graph LR"]
    cats = {}
    for node, cls in classes.items():
        cat, _ = _category(cls)
        cats.setdefault(cat, []).append(_local(node))
        text = f"{cls}<br/>{_short(labels.get(node, _local(node)))}"
        lines.append(f'  {_local(node)}["{text}"]')

    for s, p, o in g:
        if p in (RDF.type, RDFS.label) or o not in classes:
            continue  # keep only subject->object edges between typed nodes
        lines.append(f"  {_local(s)} -->|{_local(p)}| {_local(o)}")

    for cat, fill in [("site", "#b39ddb"), ("building", "#90caf9"),
                      ("equipment", _EQUIP_FILL), ("sensor", _SENSOR_FILL),
                      ("status", _STATUS_FILL), ("point", _GENERIC_FILL)]:
        if cat in cats:
            lines.append(f"  classDef {cat} fill:{fill},stroke:#555,color:#000;")
            lines.append(f"  class {','.join(cats[cat])} {cat};")
    lines.append("```")

    legend = ("**Legend:** purple=Site, blue=Building, red=Equipment/System, "
              "green=typed Sensor, orange=Status/Alarm, grey=generic Point "
              "(decoded but not typed beyond `brick:Point`).")
    return f"# Knowledge graph: {ttl_path}\n\n{legend}\n\n" + "\n".join(lines) + "\n"


def _demo():
    import tempfile, os
    ttl = ('@prefix brick: <https://brickschema.org/schema/Brick#> .\n'
           '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n'
           '<urn:b> a brick:Building ; rdfs:label "B" .\n'
           '<urn:p1> a brick:Temperature_Sensor ; rdfs:label "x.-RT401.#85" ;\n'
           '  brick:isPointOf <urn:b> .\n'
           '<urn:p2> a brick:Point ; rdfs:label "x.-LR401.#85" ;\n'
           '  brick:isPointOf <urn:b> .\n')
    p = os.path.join(tempfile.mkdtemp(), "d.ttl")
    with open(p, "w", encoding="utf-8") as f:
        f.write(ttl)
    out = render_mermaid(p)
    assert "graph LR" in out
    assert "Temperature_Sensor<br/>RT401" in out, out
    assert "-->|isPointOf|" in out
    assert "class" in out and "sensor" in out
    print("demo ok")


def main():
    ap = argparse.ArgumentParser(description="Render a Brick .ttl as a Mermaid diagram in Markdown.")
    ap.add_argument("ttl", nargs="?", help="path to a building .ttl (not the whole-site graph)")
    ap.add_argument("-o", "--output", help="markdown output path (default: stdout)")
    ap.add_argument("--demo", action="store_true", help="run the self-check and exit")
    args = ap.parse_args()

    if args.demo:
        _demo()
        return
    if not args.ttl:
        ap.error("give a .ttl path (or --demo)")

    md = render_mermaid(args.ttl)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"mermaid -> {args.output}")
    else:
        print(md)


if __name__ == "__main__":
    main()
