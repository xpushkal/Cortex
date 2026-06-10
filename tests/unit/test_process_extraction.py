"""Process extraction + faithfulness gating (M2; docs/RETRIEVAL_AND_ML.md §4.2)."""

from __future__ import annotations

from cortex.knowledge.extraction import (
    HeuristicProcessSynth,
    extract_processes,
    get_process_synth,
)
from cortex.knowledge.models import ChunkRef, Citation, Process, ProcessCluster, ProcessStep

REFUND_CHUNK = ChunkRef(
    chunk_id="chunk-refund",
    text=(
        "Refund policy. Refunds up to $500 can be issued directly by a support agent. "
        "Any refund over $500 must be routed to the finance team for approval before it "
        "is processed. Finance reviews eligibility, then approves or denies."
    ),
)
CLUSTER = ProcessCluster(
    name="Refund policy", trigger="A refund is requested", chunks=[REFUND_CHUNK]
)


def test_heuristic_synth_emits_cited_steps() -> None:
    proc = HeuristicProcessSynth().synthesize(CLUSTER)
    assert proc is not None
    assert len(proc.steps) >= 2
    # The title sentence ("Refund policy.") is not procedural -> excluded.
    assert all(s.action != "Refund policy." for s in proc.steps)
    # Every step cites the source chunk (the citation invariant, by construction).
    assert all(s.citations[0].chunk_id == "chunk-refund" for s in proc.steps)


def test_non_procedural_cluster_yields_no_process() -> None:
    cluster = ProcessCluster(
        name="Glossary",
        trigger="n/a",
        chunks=[ChunkRef(chunk_id="c", text="A widget is a unit of work. The sky is blue.")],
    )
    assert HeuristicProcessSynth().synthesize(cluster) is None
    assert extract_processes([cluster]) == []


def test_extract_processes_end_to_end_all_steps_cited() -> None:
    procs = extract_processes([CLUSTER])
    assert len(procs) == 1
    proc = procs[0]
    assert proc.name == "Refund policy"
    # Ordinals are contiguous from 1 and every step carries a citation.
    assert [s.ordinal for s in proc.steps] == list(range(1, len(proc.steps) + 1))
    assert all(s.citations for s in proc.steps)


class _FabricatingSynth:
    """Synth that emits one faithful step and one citing a chunk not in the cluster."""

    def synthesize(self, cluster: ProcessCluster) -> Process:
        return Process(
            name=cluster.name,
            trigger=cluster.trigger,
            steps=[
                ProcessStep(
                    ordinal=1,
                    action="Route the refund to the finance team for approval",
                    citations=[Citation(chunk_id="chunk-refund")],
                ),
                ProcessStep(
                    ordinal=2,
                    action="Wire the funds to an offshore account immediately",
                    citations=[Citation(chunk_id="ghost-chunk")],  # not in cluster
                ),
            ],
        )


def test_faithfulness_gate_drops_unsupported_step() -> None:
    procs = extract_processes([CLUSTER], synth=_FabricatingSynth())
    assert len(procs) == 1
    actions = [s.action for s in procs[0].steps]
    # The fabricated, mis-cited step is dropped; the faithful one survives and is re-ordinaled.
    assert any("finance team" in a for a in actions)
    assert all("offshore" not in a for a in actions)
    assert [s.ordinal for s in procs[0].steps] == [1]


def test_factory_default_is_heuristic() -> None:
    assert isinstance(get_process_synth(), HeuristicProcessSynth)
