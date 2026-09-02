"""Data contracts for the evaluation and observability layer (HW8).

Declared here and filled in by the evaluation package, the same way
models/agent.py and models/graph.py work.

    EvalCase     - one question and what it's meant to test
    NodeTiming   - one executed node, and what it cost
    EvalResult   - one case, executed and judged
    EvalSummary  - the numbers the assignment asks for

The vocabularies below are the assignment's own words, so a column in
outputs/eval_results.csv reads without a key. Where a value has to be
judged rather than derived, the field is optional and stays empty until
someone fills it in: an unjudged case is then visible as unjudged rather
than counted as a failure.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field

from genai_security_assistant.models.agent import AgentRoute
from genai_security_assistant.models.generation import AnswerStatus
from genai_security_assistant.models.graph import NodeName
from genai_security_assistant.models.tools import ToolErrorCode

# The six scenarios the assignment asks the eval set to cover, one per
# case. A scenario nobody wrote a case for is then a missing key in the
# count rather than an argument about which case covers what.
EvalKind = Literal[
    "kb_simple",
    "retrieval",
    "retrieval_may_fail",
    "no_answer",
    "tool",
    "ambiguous",
]

# The route_or_mode column. Not AgentRoute: that names the branch the
# graph took, this names how the run ended, and the two differ whenever a
# branch fails - a triage run whose lookup finds no record ends in
# fallback while its route stays triage.
RouteOrMode = Literal["RAG", "tool", "fallback", "clarification"]

# Scored by a person after reading the answer, never derived.
TaskSuccess = Literal["yes", "partial", "no"]
Quality = Literal["good", "partial", "bad"]

# Groundedness carries a fourth value the other scales do not. A run that
# retrieved nothing has no context to be grounded in, and scoring it bad
# would blame it for a question it was never asked.
Groundedness = Literal["good", "partial", "bad", "not_applicable"]

# Which of the two runs produced a row. Carried on every trace line even
# though each file holds one mode: lines get concatenated and grepped, and
# a line that can't say where it came from costs more than a repeated
# column.
RunMode = Literal["live", "cached"]

# The errors column. No "none" member: an empty list already says nothing
# went wrong, and two spellings of that eventually disagree. The report
# prints "none" where the list is empty.
EvalError = Literal[
    "wrong_route",
    "wrong_mode",
    "tool_error",
    "no_citations",
    "unsupported_citation",
    "wrong_retrieval",
    "missing_context",
    "hallucination",
]

# Which half of EvalError comes from where. Keep both in step with the
# Literal above: a test asserts they cover it exactly and do not overlap,
# so a new error type can't be added without deciding who detects it.
DETECTED_ERRORS: tuple[EvalError, ...] = (
    "wrong_route",
    "wrong_mode",
    "tool_error",
    "no_citations",
    "unsupported_citation",
)
JUDGED_ERRORS: tuple[EvalError, ...] = (
    "wrong_retrieval",
    "missing_context",
    "hallucination",
)


class EvalCase(BaseModel):
    """One question, why it's in the set, and how it was judged.
    Everything down to 'note' is read from configs/eval_cases.yaml before
    the graph runs. The five fields below it are written back by hand
    afterwards and are absent until then.
    """

    id: str
    question: str
    kind: EvalKind
    expected_route: AgentRoute
    expected_mode: RouteOrMode
    expected_behavior: str
    # Read by confirm_write. Set only on a case meant to reach the write.
    confirm: bool = False
    note: str = ""

    task_success: TaskSuccess | None = None
    # Overrides the derived value on EvalResult where a reader disagrees
    # with it. The disagreements are worth reporting: they are the measure
    # of how far an automatic grounding check can be trusted here.
    groundedness: Groundedness | None = None
    answer_quality: Quality | None = None
    # The JUDGED_ERRORS half. Nothing stops a detected one being written
    # here, and nothing needs to: EvalResult.errors removes repeats.
    errors: list[EvalError] = Field(default_factory=list)
    comment: str = ""


class NodeTiming(BaseModel):
    """One executed node: what it wrote, what it called, what it cost.
    One line of outputs/eval_traces_{live,cached}.jsonl. NodeRecord in
    models/graph.py already says what a node did; this adds the two things
    a trace needs and a state doesn't - when it ran and how long it took.
    """

    run_mode: RunMode
    case_id: str
    sequence: int = Field(ge=1)
    node: NodeName
    # Milliseconds as a float, not an int: a node that only reads the
    # state finishes in tens of microseconds, and a whole cached run
    # would be a column of zeros. EvalResult.latency_ms stays an int,
    # because that's the column the assignment asks for.
    duration_ms: float = Field(ge=0)
    # The state keys this node returned, minus 'nodes', which every node
    # writes. The same list run_traced already produces.
    wrote: list[str] = Field(default_factory=list)
    tool_name: str | None = None
    # Three values, not two. None means this node called nothing, so that
    # "made no call" and "made one that could have been replayed and was
    # not" stay apart. Three of the four tools read a file in this
    # repository and have no cache to hit; their False says that, not
    # that a request went out.
    from_cache: bool | None = None
    error_code: ToolErrorCode | None = None
    note: str = ""


class EvalResult(BaseModel):
    """One case, executed: what the graph did and how it was judged.
    Holds the case rather than copying its fields, so expected and actual
    sit side by side and can't drift apart.
    """

    number: int = Field(ge=1)
    case: EvalCase
    run_mode: RunMode

    answer: str
    route: AgentRoute | None
    route_or_mode: RouteOrMode
    # None where no answerer ran at all, which is every clarification run
    # and every triage run that halted before retrieve_guidance.
    status: AnswerStatus | None
    tools_used: list[str] = Field(default_factory=list)
    # What retrieval returned, and the subset the answer pointed at. Both,
    # because the gap between them is what "three of five chunks
    # contributed nothing" is measured from.
    retrieved_chunks: list[str] = Field(default_factory=list)
    cited_chunks: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    best_score: float | None = None

    latency_ms: int = Field(ge=0)
    nodes: list[NodeTiming] = Field(default_factory=list)
    # True when nothing in this run reached the network. Counted over the
    # cacheable nodes only - see reached_network in evaluation/labels.py.
    from_cache: bool = False

    groundedness_auto: Groundedness
    detected_errors: list[EvalError] = Field(default_factory=list)

    @computed_field
    @property
    def groundedness(self) -> Groundedness:
        """The judged value where there is one, the derived value otherwise."""
        return self.case.groundedness or self.groundedness_auto

    @computed_field
    @property
    def errors(self) -> list[EvalError]:
        """Detected then judged errors, in that order, without repeats."""
        return list(dict.fromkeys([*self.detected_errors, *self.case.errors]))

    @computed_field
    @property
    def judged(self) -> bool:
        """Whether a person has scored this case yet."""
        return self.case.task_success is not None

    @computed_field
    @property
    def node_ms(self) -> float:
        """What the nodes themselves spent, in milliseconds."""
        return round(sum(row.duration_ms for row in self.nodes), 3)

    @computed_field
    @property
    def overhead_ms(self) -> float:
        """Wall clock minus the nodes: what the framework spent merging.
        Small beside a network call and large beside none, which is the
        whole reason it's a column instead of a footnote.
        """
        return round(self.latency_ms - self.node_ms, 3)

class EvalSummary(BaseModel):
    """The observability metrics for one run.
    Three rates are None until the cases are judged, because a rate over
    nothing is not zero. groundedness_good_rate is not one of them: every
    row carries a derived value from the first run onwards.
    """

    run_mode: RunMode
    total_cases: int = Field(ge=1)
    judged_cases: int = Field(ge=0)

    success_rate: float | None = None
    partial_rate: float | None = None
    failure_rate: float | None = None

    # Over every case, which is the assignment's formula.
    groundedness_good_rate: float
    # The same count over the cases where groundedness applies at all. A
    # set that is a third tool calls cannot score above the share that
    # retrieved anything, and the headline rate alone hides that.
    applicable_cases: int = Field(ge=0)
    groundedness_good_rate_applicable: float | None = None

    average_latency_ms: int = Field(ge=0)
    # The average alone would report a tool call and a refused question as
    # one middling number, and this set contains both by design.
    median_latency_ms: int = Field(ge=0)
    max_latency_ms: int = Field(ge=0)
    slowest_case: str

    # Every error type seen, plus "none" for the cases that had none.
    error_counts: dict[str, int] = Field(default_factory=dict)

    @computed_field
    @property
    def top_error_types(self) -> list[tuple[str, int]]:
        """Error types by how often they occurred, commonest first.
        Ties break by name so two runs of the same data print the same
        order.
        """
        return sorted(self.error_counts.items(), key=lambda pair: (-pair[1], pair[0]))
