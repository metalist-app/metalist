"""Build one ordered, token-bounded evidence payload from a frozen scope."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from app.services.agent.evidence_serialization import EvidenceNoteTokenSource
from app.services.agent.evidence_serialization import EvidenceTreeTokenSource
from app.services.agent.evidence_serialization import estimate_cached_root_tree_tokens
from app.services.agent.evidence_serialization import serialize_evidence_note_payload
from app.services.agent.evidence_serialization import serialize_evidence_result_trees
from app.services.agent.note_aliases import NoteAliases
from app.services.agent.retrieval_settings import AgentRetrievalSettings
from app.services.agent.scope import ScopedSearchSnapshot
from app.services.agent.token_estimation import estimate_input_tokens

# The first two batches for a model with no saved timing, as shares of a batch: a tenth, a fifth.
_TIMING_PROBE_DIVISORS = (10, 5)


@dataclass(frozen=True, slots=True)
class InvestigationEvidencePayload:
    """The run's single evidence payload."""

    evidence_note_ids: tuple[str, ...]
    result_tree_ids: tuple[str, ...]
    result_trees: tuple[dict[str, object], ...]
    returned_approximate_token_count: int


@dataclass(frozen=True, slots=True)
class RootPrefixRetention:
    original_note_count: int
    original_result_tree_count: int
    retained_note_count: int
    retained_result_tree_count: int
    retained_approximate_token_count: int
    retained_root_ids: tuple[str, ...]
    dropped_root_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RootTreeRead:
    """Whole root trees read for one tool call, in view order, within the budget.

    unread_root_ids fit no more in this read and can be requested next;
    too_large_root_ids exceed the budget on their own and can never be read;
    unknown_ids are not in the frozen view.
    """

    payload: InvestigationEvidencePayload
    unread_root_ids: tuple[str, ...]
    too_large_root_ids: tuple[str, ...]
    unknown_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompleteRootBatchPlan:
    """Every visible root tree partitioned into ordered evidence payloads."""

    batches: tuple[InvestigationEvidencePayload, ...]
    note_count: int
    result_tree_count: int
    approximate_token_count: int


class InvestigationState:
    """Run-local frozen scope reduced once to an ordered complete-root prefix."""

    def __init__(
        self,
        *,
        snapshot: ScopedSearchSnapshot,
        settings: AgentRetrievalSettings,
    ) -> None:
        if not isinstance(snapshot, ScopedSearchSnapshot):
            raise TypeError("InvestigationState requires ScopedSearchSnapshot")
        if not isinstance(settings, AgentRetrievalSettings):
            raise TypeError("InvestigationState requires AgentRetrievalSettings")
        self._snapshot = snapshot
        self._settings = settings
        self._retained_root_ids = snapshot.ordered_root_ids
        self._retained_note_ids = snapshot.ordered_note_ids
        self._retention_was_applied = False
        self._structure_by_root: dict[str, list[EvidenceTreeTokenSource]] = {
            root_id: [] for root_id in snapshot.ordered_root_ids
        }
        for note_id, node in snapshot.tree_nodes_by_id.items():
            self._structure_by_root[node.root_note_id].append(EvidenceTreeTokenSource(
                note_id=note_id, parent_id=node.parent_id, child_ids=node.child_ids,
            ))

    @classmethod
    def start(
        cls,
        *,
        snapshot: ScopedSearchSnapshot,
        settings: AgentRetrievalSettings,
    ) -> InvestigationState:
        return cls(snapshot=snapshot, settings=settings)

    @property
    def snapshot(self) -> ScopedSearchSnapshot:
        return self._snapshot

    @cached_property
    def note_aliases(self) -> NoteAliases:
        """The short note IDs (n1, n2…) a summary's requests carry: the chat's, from the same
        snapshot, so its answer's citations translate as the chat's do (note_aliases.py)."""
        return NoteAliases.from_snapshot(self._snapshot)

    @property
    def max_page_approximate_tokens(self) -> int:
        return self._settings.max_page_approximate_tokens

    def retain_root_prefix_within_token_budget(self, *, reserved_approximate_tokens: int) -> RootPrefixRetention:
        assert 0 <= reserved_approximate_tokens <= self._settings.max_page_approximate_tokens
        scope_token_limit = self._settings.max_page_approximate_tokens - reserved_approximate_tokens
        if self._retention_was_applied:
            raise RuntimeError("Evidence root-prefix retention may run only once")
        self._retention_was_applied = True
        note_ids_by_root_id = self._note_ids_by_root_id()
        retained_root_ids: list[str] = []
        retained_token_count = 0
        for root_id in self._snapshot.ordered_root_ids:
            root_token_count = self._full_root_token_cost(
                root_id=root_id,
                note_ids=note_ids_by_root_id[root_id],
            )
            if retained_token_count + root_token_count > (
                scope_token_limit
            ):
                break
            retained_root_ids.append(root_id)
            retained_token_count += root_token_count
        if self._snapshot.ordered_root_ids and not retained_root_ids:
            first_root_id = self._snapshot.ordered_root_ids[0]
            first_root_tokens = self._full_root_token_cost(
                root_id=first_root_id,
                note_ids=note_ids_by_root_id[first_root_id],
            )
            raise ValueError(
                "The first complete result tree requires approximately "
                f"{first_root_tokens:,} tokens, exceeding the configured single "
                "evidence payload limit of "
                f"{scope_token_limit:,} tokens after reserving selected-note context"
            )
        retained_root_ids_tuple = tuple(retained_root_ids)
        retained_root_id_set = set(retained_root_ids_tuple)
        retained_note_ids = tuple(
            note_id
            for note_id in self._snapshot.ordered_note_ids
            if self._snapshot.notes_by_id[note_id].root_note_id
            in retained_root_id_set
        )
        self._retained_root_ids = retained_root_ids_tuple
        self._retained_note_ids = retained_note_ids
        return RootPrefixRetention(
            original_note_count=self._snapshot.note_count,
            original_result_tree_count=self._snapshot.result_tree_count,
            retained_note_count=len(retained_note_ids),
            retained_result_tree_count=len(retained_root_ids_tuple),
            retained_approximate_token_count=retained_token_count,
            retained_root_ids=retained_root_ids_tuple,
            dropped_root_ids=self._snapshot.ordered_root_ids[
                len(retained_root_ids_tuple) :
            ],
        )

    def current_scope_payload(self) -> InvestigationEvidencePayload:
        if not self._retention_was_applied:
            raise RuntimeError("Retain the token-bounded evidence prefix first")
        result_trees = self._serialize_full_result_trees()
        token_count = estimate_input_tokens(result_trees)
        if token_count > self._settings.max_page_approximate_tokens:
            raise RuntimeError(
                "Serialized evidence payload exceeded its precomputed token budget"
            )
        return InvestigationEvidencePayload(
            evidence_note_ids=self._retained_note_ids,
            result_tree_ids=self._retained_root_ids,
            result_trees=result_trees,
            returned_approximate_token_count=token_count,
        )

    def read_root_trees(self, *, requested_ids: tuple[str, ...]) -> RootTreeRead:
        """Read whole trees for requested notes (any note in a tree selects it).

        With no requested ids, read the view from its first tree. Trees are
        taken in view order until the next one no longer fits the budget.
        """
        assert isinstance(requested_ids, tuple)
        unknown_ids: list[str] = []
        wanted_root_ids: set[str] = set()
        for note_id in requested_ids:
            if note_id in self._snapshot.notes_by_id:
                wanted_root_ids.add(self._snapshot.notes_by_id[note_id].root_note_id)
            elif note_id in self._snapshot.tree_nodes_by_id:
                wanted_root_ids.add(self._snapshot.tree_nodes_by_id[note_id].root_note_id)
            elif note_id not in unknown_ids:
                unknown_ids.append(note_id)
        candidate_root_ids = self._snapshot.ordered_root_ids
        if requested_ids:
            candidate_root_ids = tuple(
                root_id for root_id in candidate_root_ids if root_id in wanted_root_ids
            )
        token_limit = self._settings.max_page_approximate_tokens
        note_ids_by_root_id = self._note_ids_by_root_id()
        read_root_ids: list[str] = []
        unread_root_ids: list[str] = []
        too_large_root_ids: list[str] = []
        read_token_count = 0
        for root_id in candidate_root_ids:
            root_token_count = self._full_root_token_cost(
                root_id=root_id, note_ids=note_ids_by_root_id[root_id],
            )
            if root_token_count > token_limit:
                too_large_root_ids.append(root_id)
            elif unread_root_ids or read_token_count + root_token_count > token_limit:
                unread_root_ids.append(root_id)
            else:
                read_root_ids.append(root_id)
                read_token_count += root_token_count
        payload = self._payload_for_roots(tuple(read_root_ids))
        if payload.returned_approximate_token_count > token_limit:
            raise RuntimeError("Serialized root-tree read exceeded its precomputed token budget")
        return RootTreeRead(
            payload=payload,
            unread_root_ids=tuple(unread_root_ids),
            too_large_root_ids=tuple(too_large_root_ids),
            unknown_ids=tuple(unknown_ids),
        )

    def plan_complete_root_batches(
        self,
        *,
        reserved_approximate_tokens: int,
        with_timing_probes: bool,
    ) -> CompleteRootBatchPlan:
        """Partition the entire frozen scope without splitting a root tree. For a model whose
        timing is not known yet, the first two batches are small and of different sizes: real
        batches whose times separate its startup cost from its time per token."""
        assert 0 <= reserved_approximate_tokens <= (
            self._settings.max_page_approximate_tokens
        )
        batch_limit = (
            self._settings.max_page_approximate_tokens
            - reserved_approximate_tokens
        )
        note_ids_by_root_id = self._note_ids_by_root_id()
        root_costs: list[tuple[str, int]] = []
        for root_id in self._snapshot.ordered_root_ids:
            root_token_count = self._full_root_token_cost(
                root_id=root_id,
                note_ids=note_ids_by_root_id[root_id],
            )
            if root_token_count > batch_limit:
                raise ValueError(
                    f"The complete result tree {root_id} requires approximately "
                    f"{root_token_count:,} tokens, exceeding the configured "
                    f"per-batch evidence limit of {batch_limit:,} tokens"
                )
            root_costs.append((root_id, root_token_count))
        needs_probes = with_timing_probes and sum(cost for _root_id, cost in root_costs) > batch_limit

        def limit_of_batch(batch_index: int) -> int:
            if needs_probes and batch_index < len(_TIMING_PROBE_DIVISORS):
                return batch_limit // _TIMING_PROBE_DIVISORS[batch_index]
            return batch_limit

        batches: list[InvestigationEvidencePayload] = []
        batch_root_ids: list[str] = []
        batch_token_count = 0
        for root_id, root_token_count in root_costs:
            if batch_root_ids and batch_token_count + root_token_count > limit_of_batch(len(batches)):
                batches.append(self._payload_for_roots(tuple(batch_root_ids)))
                batch_root_ids = []
                batch_token_count = 0
            batch_root_ids.append(root_id)
            batch_token_count += root_token_count
        if batch_root_ids:
            batches.append(self._payload_for_roots(tuple(batch_root_ids)))
        if any(
            batch.returned_approximate_token_count > batch_limit
            for batch in batches
        ):
            raise RuntimeError(
                "Serialized complete-root batch exceeded its precomputed token budget"
            )
        planned_root_ids = tuple(
            root_id for batch in batches for root_id in batch.result_tree_ids
        )
        planned_note_ids = tuple(
            note_id for batch in batches for note_id in batch.evidence_note_ids
        )
        if planned_root_ids != self._snapshot.ordered_root_ids:
            raise RuntimeError("Complete-root batching changed frozen root order")
        if planned_note_ids != self._snapshot.ordered_note_ids:
            raise RuntimeError("Complete-root batching changed frozen note order")
        return CompleteRootBatchPlan(
            batches=tuple(batches),
            note_count=len(planned_note_ids),
            result_tree_count=len(planned_root_ids),
            approximate_token_count=sum(
                batch.returned_approximate_token_count for batch in batches
            ),
        )

    def _payload_for_roots(
        self,
        root_ids: tuple[str, ...],
    ) -> InvestigationEvidencePayload:
        root_id_set = set(root_ids)
        note_ids = tuple(
            note_id
            for note_id in self._snapshot.ordered_note_ids
            if self._snapshot.notes_by_id[note_id].root_note_id in root_id_set
        )
        result_trees = self._serialize_result_trees(
            root_ids=root_ids,
            note_ids=note_ids,
        )
        return InvestigationEvidencePayload(
            evidence_note_ids=note_ids,
            result_tree_ids=root_ids,
            result_trees=result_trees,
            returned_approximate_token_count=estimate_input_tokens(result_trees),
        )

    def _note_ids_by_root_id(self) -> dict[str, list[str]]:
        note_ids_by_root_id: dict[str, list[str]] = {
            root_id: [] for root_id in self._snapshot.ordered_root_ids
        }
        for note_id in self._snapshot.ordered_note_ids:
            root_id = self._snapshot.notes_by_id[note_id].root_note_id
            if root_id not in note_ids_by_root_id:
                raise RuntimeError("Frozen note refers to an unordered root")
            note_ids_by_root_id[root_id].append(note_id)
        return note_ids_by_root_id

    def _full_root_token_cost(self, *, root_id: str, note_ids: list[str]) -> int:
        evidence_notes = tuple(
            EvidenceNoteTokenSource(
                note_id=note_id,
                content_text=self._snapshot.notes_by_id[note_id].content_text,
                explicit_tag_terms=(
                    self._snapshot.notes_by_id[note_id].explicit_tag_terms
                ),
                proposed_tag_terms=(
                    self._snapshot.notes_by_id[note_id].proposed_tag_terms
                ),
                created_at=self._snapshot.notes_by_id[note_id].created_at,
                updated_at=self._snapshot.notes_by_id[note_id].updated_at,
            )
            for note_id in note_ids
        )
        structure_nodes = tuple(self._structure_by_root[root_id])
        return estimate_cached_root_tree_tokens(
            root_id=root_id,
            evidence_notes=evidence_notes,
            structure_nodes=structure_nodes,
        )

    def _serialize_full_result_trees(self) -> tuple[dict[str, object], ...]:
        return self._serialize_result_trees(
            root_ids=self._retained_root_ids,
            note_ids=self._retained_note_ids,
        )

    def _serialize_result_trees(
        self,
        *,
        root_ids: tuple[str, ...],
        note_ids: tuple[str, ...],
    ) -> tuple[dict[str, object], ...]:
        serialized_by_id = {
            note_id: serialize_evidence_note_payload(
                note_id=note.note_id,
                content_text=note.content_text,
                explicit_tag_terms=note.explicit_tag_terms,
                proposed_tag_terms=note.proposed_tag_terms,
                created_at=note.created_at,
                updated_at=note.updated_at,
            )
            for note_id in note_ids
            for note in (self._snapshot.notes_by_id[note_id],)
        }
        return serialize_evidence_result_trees(
            root_ids=root_ids,
            evidence_payloads_by_id=serialized_by_id,
            parent_id_by_id={
                note_id: node.parent_id
                for note_id, node in self._snapshot.tree_nodes_by_id.items()
            },
            child_ids_by_id={
                note_id: node.child_ids
                for note_id, node in self._snapshot.tree_nodes_by_id.items()
            },
        )
