## What moved, and what did not

At the level of what the workflow decides, the port replaced one thing: how
it chooses what runs next. `agent_flow.run_triage` called eight methods in
order and read their return values to know whether to carry on.
`langgraph_flow.build_graph` declares the same order as edges, and a
function under each branching node reads the state to choose the next one.

Everything the workflow decides stayed where it was. `agent_router.py`
routes, `triage_rules.py` concludes, `tools/registry.py` calls,
`RAGAnswerer` retrieves, and `agent_flow.final_answer` still composes every
answer both implementations give.

`test_both_implementations_answer_one_goal_identically`, in
`tests/unit/orchestration/test_langgraph_flow.py` and parametrized over all
seven scenarios, runs each goal through both and asserts that the route,
the exposure and the answer match. The paragraph above is therefore
checkable, which is the only reason it is worth reading: a port that agreed
only on the exposed path would pass one of those seven and fail the rest.

What did change, beyond the ordering: how the state is declared, how it is
updated, how the trace accumulates, and one adapter between the two state
representations. Those are the subject of the costs below.

## What the framework gave

**Branch points became countable.** The graph declares five conditional
edges, which render as eleven dotted arrows. HW6 made the same five
decisions in `run` and `run_triage` - `if not self.lookup_cve(state):
return`, `if state.exposure != "exposed": return` - with the checks that
fed them buried inside the step methods. Counting them meant reading both
levels.

**The trace stopped depending on the author remembering it.** HW6 appended
to `state.steps` by hand, in every step, through `add_step`. Here the
runtime reports each node's update on its own, and `operator.add`
concatenates whatever records the nodes returned. The notes, requests and
observations inside those records still come from the node - a node that
returns none contributes none - but nothing can now reorder them or drop
what an earlier node wrote, which `state.steps = [...]` could have.

**The report gained a column HW6 could not fill.**
`stream(stream_mode=["updates", "values"])` reports each node's return
value separately from the merged state, so `outputs/langgraph_examples.md`
can say which fields each node was responsible for. A step mutating a
shared object leaves no such record.

**Convergence became visible.** Seven edges reach `build_answer`. HW6 had
the same convergence - `run()` composed the answer after the plan, for all
three routes - and nothing showed it.

## What the framework cost

**A write gate that failed open.**

In HW6 the confirmation call and the branch that consumed its result sat on
adjacent lines of one method: `if not self.confirm_write(state): return`.
The consumer could not exist without the producer running first.

In the graph they are two separate pieces of configuration - a node that
produces the authorization, and an edge that consumes it by reading a field
off the state. That separation is what let a default value be mistaken for
approval. The first version of the edge read `pending_confirmation`, whose
default is `false`, so a graph whose gate had been rewired around would have
written every time, including when the caller had not confirmed. The failure
was reproduced while porting; the regression tests in this repository hold
the current selector and the write node to the opposite.

The fix is a second field, `write_authorized: bool | None`, that only the
gate writes and whose default is `None` - "nobody decided" told apart from
"decided no". The general form: **a node that never runs still leaves its
field at a default, so a safety decision needs a value that means the
decision was never made.** HW6 did not expose this failure mode, because
there the decision was consumed immediately as a return value rather than
persisted for a separate edge to read later.

The same reading turned up a second thing, older than this port. HW6's own
scenario prose calls the confirmation "two independent refusals" - the
workflow's gate, and `BaseTool.run` refusing a write whose request is not
confirmed. But both implementations passed `confirmed=True` into that
request unconditionally, so the second refusal was answering a claim the
first one had made about itself. The graph reads `write_authorized` into
that flag now, which is what makes the two independent. HW6 still does not:
the implementations differ here on purpose, and
`test_the_write_node_refuses_a_state_the_gate_never_authorized` calls the
write node directly, the way a rewiring mistake would, to hold the graph to
it.

**The signature stopped documenting the branch.** HW6 gave steps that could
end a run a return type of `bool`; reading a signature told you whether a
step was a branch. Every node here returns `dict[str, Any]`. What was
gained in one place - all branches visible in `build_graph` - was lost in
another.

**Two representations of one state.** `TriageState` is a TypedDict because
that fits the partial-update model these nodes use; LangGraph would also
have taken a dataclass or a Pydantic model. `AgentState` stays a Pydantic
model because `final_answer` reads attributes. `as_agent_state` bridges
them, and `plain` in the CLI exists because a TypedDict has no
`model_dump`. Around forty lines exist only because of the second
representation.

**Nineteen lockfile packages for one direct dependency.** Adding
`langgraph 1.2.11` added nineteen packages in total: `langgraph` itself,
`langchain-core`, `langsmith`, `requests`, `orjson`, `zstandard`,
`websockets`, and twelve others. Beyond LangGraph itself, application code
imports exactly one symbol from that set: `Edge`, from the transitive
`langchain-core`, in `graph_diagram.py`. The rest are framework internals.
One of them, `langsmith`, is a tracing client that stays quiet unless
`LANGSMITH_TRACING` is set - a runtime behaviour this repository did not
have before.

**The framework's own diagram did not scale.** `draw_mermaid()` on twelve
nodes with seven edges into one of them renders a thicket, and
`draw_mermaid_png()` renders it by sending the graph to `mermaid.ink`,
adding a third-party call to a workflow whose replayed examples otherwise
run with no network and no key. `graph_diagram.py`, 96 lines, draws the
same nineteen edges with the plan boxed and the branching nodes coloured.

## The cost, measured

| | HW6 | HW7 |
|---|---|---|
| the flow | `agent_flow.py`, 358 | `langgraph_flow.py`, 556 |
| the state | `models/agent.py`, 149 | `models/graph.py`, 191 |
| drawing it | — | `graph_diagram.py`, 96 |
| the CLI | 147 | 234 |
| the report generator | 242 | 268 |
| the tests | 175 | 236 |
| direct dependencies | 0 | 1, adding 19 to the lockfile |

The flow grew by 55 per cent and the state by 28. Around forty of those
240 added lines - roughly a sixth - are the adapter and serialization code
the second state representation brought with it.

## What the two produce

Seven scenarios, both implementations, the same answer for each. What
differs is how much of a run each one names:

| Scenario | HW6 steps of 8 | HW7 nodes of 12 |
|---|---|---|
| CVE-2025-68664, confirmed | 8 | 10 |
| CVE-2025-68664, unconfirmed | 7 | 9 |
| CVE-2025-67644, patched | 3 | 5 |
| CVE-2024-5565, not affected | 3 | 5 |
| CVE-2023-99999, no record | 1 | 3 |
| prompt injection, guidance | 1 | 3 |
| LangChain bug, clarification | 1 | 3 |

The constant two is routing and answer composition. HW6 ran both, outside
its plan and outside its count; the graph has no outside, so both are nodes
and both are in the trace.

## The verdict for this size

For three routes, eight steps, no parallel branches and no cycles, the
framework cost more than it returned. Every conditional edge here replaced
an `if` that was already correct and already tested.

Two things it returned that the line count does not show: the graph is now
a document, and the shape of a run is reported by the runtime rather than
assembled by hand. On a workflow twice this size, written by more than one
person, both would matter more than the fifty per cent.

## What would change the verdict

HW6 wrote down a limitation it could not fix: *"a run stopped at the
confirmation gate must be started again with `--confirm`."*

LangGraph answers that with `interrupt()` and a checkpointer. Compiling with
a checkpointer and invoking under a stable thread id preserves the state
reached so far; the caller resumes with `Command(resume=approval)`, and the
lookup, inventory, retrieval and owner nodes do not run again. Measured on a
throwaway graph while writing this: after a resume, the nodes before the
interrupt had executed once, and only the interrupting node had executed
twice.

That second half is the part worth writing down. **A node containing
`interrupt()` restarts from its first line when the run resumes**, so
anything it does before the interrupt happens twice. A gate that only reads
a flag is safe; one that logged, notified or wrote would not be.

Not implemented here. It is a bounded extension rather than a small change:
it needs a checkpointer, a thread id the CLI does not currently have, and a
resume path alongside `--confirm`. Named because it is the honest answer to
whether the framework was worth it - for what this workflow does today,
barely; for the one thing it was already documented as unable to do, the
framework is what turns a redesign into that bounded extension.
