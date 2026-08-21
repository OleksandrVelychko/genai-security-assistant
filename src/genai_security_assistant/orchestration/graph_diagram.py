"""The graph, drawn so a reader can see where it forks (HW7).

draw_mermaid() renders every node and every edge, and on twelve nodes with
eleven conditional branches what it renders is a thicket: seven edges reach
build_answer from seven different depths, and nothing on the page says which
nodes are the ones that decide.

This draws the same nineteen edges and adds the two things a reader needs:

    a box     around the eight steps HW6 ran as a plan
    a color  on every node a conditional edge leaves

Neither is written down here. The box is TRIAGE_PLAN, the tuple agent_flow
already runs in order; the color comes from edge.conditional, which
LangGraph sets on an edge that came from add_conditional_edges. Move a
branch or add a node and the picture follows without anyone editing it.
"""

from __future__ import annotations

from langchain_core.runnables.graph import Edge
from langgraph.graph.state import CompiledStateGraph

from genai_security_assistant.orchestration.agent_flow import TRIAGE_PLAN

# The two nodes LangGraph adds around every graph.
ENTRY, EXIT = "__start__", "__end__"

# The gate is a fork like the other four and is colored apart from them,
# because what it decides is not which answer to give but whether anything
# is written at all.
GATE = "confirm_write"

# Light fills with the text color set explicitly. A dark GitHub theme
# recolors text and leaves a fill alone, so a fill without a color beside
# it renders as pale text on pale paper for half the readers.
STYLES = (
    "classDef branch fill:#fff3cd,stroke:#8a6d00,color:#1a1a1a",
    "classDef gate fill:#f8d7da,stroke:#9b2226,color:#1a1a1a",
)


def arrow(edge: Edge) -> str:
    """One edge, dotted when a function chose it and solid when nothing did."""
    if edge.conditional:
        return f"{edge.source} -. {edge.data} .-> {edge.target}"
    return f"{edge.source} --> {edge.target}"


def readable_mermaid(compiled: CompiledStateGraph) -> str:
    """Render the compiled graph as Mermaid, grouped and colored.

    Sorted twice, and both sorts matter. Edges are read in a stable order so
    two runs of this produce the same text and a changed graph shows up as a
    small diff rather than a reshuffled file. The ones inside the box are
    then put back into plan order, because Mermaid lays a subgraph out
    roughly in the order its edges are declared, and plan order is the one a
    reader is following.
    """
    edges = sorted(compiled.get_graph().edges, key=lambda e: (e.source, e.target))
    step = {name: number for number, name in enumerate(TRIAGE_PLAN)}

    inside: list[Edge] = []
    outside: list[Edge] = []
    for edge in edges:
        in_plan = edge.source in step and edge.target in step
        (inside if in_plan else outside).append(edge)
    inside.sort(key=lambda e: (step[e.source], step[e.target]))

    # Every node a conditional edge leaves. Derived, not listed: this is the
    # question the picture exists to answer, and a hand-kept list would be
    # the first thing to go stale.
    forks = sorted({e.source for e in edges if e.conditional} - {GATE})
    before_plan = (ENTRY, "classify_request")

    lines = [
        "graph TD",
        f"    {ENTRY}([START])",
        f"    {EXIT}([END])",
        "",
    ]
    lines += [f"    {arrow(e)}" for e in outside if e.source in before_plan]
    lines += [
        "",
        '    subgraph plan ["the eight steps HW6 ran as a plan"]',
        "    direction TB",
    ]
    lines += [f"        {arrow(e)}" for e in inside]
    lines += ["    end", ""]
    lines += [f"    {arrow(e)}" for e in outside if e.source not in before_plan]
    lines += ["", *(f"    {style}" for style in STYLES)]
    lines += [
        f"    class {','.join(forks)} branch",
        f"    class {GATE} gate",
    ]
    return "\n".join(lines)
