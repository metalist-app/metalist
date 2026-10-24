"""Fixed regression scenarios and expectations, without captured prompts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Message(StrictModel):
    role: Literal["system", "developer", "user", "assistant"]
    content: str


class ConversationMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: str


class PreviousOutput(StrictModel):
    role: Literal["assistant"]
    from_step: int = Field(ge=0)


class ScopeFixture(StrictModel):
    scope_kind: Literal["search", "all_notes", "untagged", "reference"]
    label: str
    search_query: str
    sort_mode: str
    matching_note_count: int = Field(ge=0)
    matching_result_tree_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self):
        if self.matching_result_tree_count > self.matching_note_count:
            raise ValueError("Result tree count cannot exceed note count")
        return self


class SelectedNoteFixture(StrictModel):
    status: Literal["none", "available", "unavailable"]
    note_id: str
    content_text: str
    tags: str

    @model_validator(mode="after")
    def validate_disclosure(self):
        if self.status == "available" and not self.note_id:
            raise ValueError("Available selected note requires an ID")
        if self.status != "available" and any((self.note_id, self.content_text, self.tags)):
            raise ValueError("Absent or excluded selections cannot carry note data")
        return self


class SelectedTreeNoteFixture(StrictModel):
    note_id: str = Field(min_length=1)
    parent_id: str
    content_text: str
    tags: str


class SelectedHtmlTreeNoteFixture(StrictModel):
    note_id: str = Field(min_length=1)
    parent_id: str
    content_html: str
    tags: str
    cached_url_titles: dict[str, str]


class SelectedTreeFixture(StrictModel):
    status: Literal["available"]
    note_id: str = Field(min_length=1)
    tree_notes: list[SelectedTreeNoteFixture | SelectedHtmlTreeNoteFixture] = Field(min_length=1)


class UnavailableSelectionFixture(StrictModel):
    status: Literal["unavailable"]
    reason: Literal["blacklisted", "not_whitelisted", "password_protected", "search_redacted", "not_found", "unspecified"]


class SummaryBatchContext(StrictModel):
    stage: Literal["summary_batch"]
    scope: ScopeFixture
    selected_note: SelectedNoteFixture | SelectedTreeFixture | UnavailableSelectionFixture
    result_trees: list[dict] = Field(min_length=1)
    result_tree_ids: list[str] = Field(min_length=1)
    batch_index: int = Field(ge=0)
    batch_count: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_batch_index(self):
        if self.batch_index >= self.batch_count:
            raise ValueError("Summary batch index must be inside batch count")
        return self


class SummaryFinalContext(StrictModel):
    stage: Literal["summary_final"]
    scope: ScopeFixture
    selected_note: SelectedNoteFixture | SelectedTreeFixture | UnavailableSelectionFixture
    summaries: list[dict] = Field(min_length=1)


class Criterion(StrictModel):
    id: str = Field(min_length=1)
    instruction: str = Field(min_length=1)


class ActionExpectation(StrictModel):
    kind: Literal["action"]
    alternatives: list[dict] = Field(min_length=1)


class OutputExpectation(StrictModel):
    kind: Literal["output"]
    criteria: list[Criterion] = Field(min_length=1)
    reference_facts: str

    @model_validator(mode="after")
    def unique_criteria(self):
        ids = [criterion.id for criterion in self.criteria]
        if len(set(ids)) != len(ids):
            raise ValueError("Criterion IDs must be unique")
        return self


class Step(StrictModel):
    conversation: list[ConversationMessage | PreviousOutput] = Field(min_length=1)
    context: Annotated[
        SummaryBatchContext | SummaryFinalContext,
        Field(discriminator="stage"),
    ]
    expectation: ActionExpectation | OutputExpectation

    @model_validator(mode="after")
    def validate_contract(self):
        if self.conversation[-1].role != "user":
            raise ValueError("Conversation must end with the current user request")
        is_structured = self.context.stage == "summary_batch"
        if self.expectation.kind == "action" and not is_structured:
            raise ValueError("Action expectations require a structured step")
        if self.expectation.kind == "action" and any(not item for item in self.expectation.alternatives):
            raise ValueError("Action alternatives must assert at least one field")
        return self


class RegressionCase(StrictModel):
    schema_version: Literal[2]
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    reviewed: bool
    model: str = Field(min_length=1)
    thinking_level: Literal["off", "low", "medium", "high"]
    steps: list[Step] = Field(min_length=1)
    provenance: dict

    @model_validator(mode="after")
    def validate_previous_steps(self):
        for index, step in enumerate(self.steps):
            for message in step.conversation:
                if isinstance(message, PreviousOutput) and message.from_step >= index:
                    raise ValueError("Previous output must refer to an earlier step")
        return self


class PreparedStep(StrictModel):
    kind: Literal["structured", "text"]
    messages: list[Message | PreviousOutput]
    response_model: str
    response_schema: dict
    expectation: ActionExpectation | OutputExpectation


class PreparedCase(StrictModel):
    id: str
    model: str
    thinking_level: Literal["off", "low", "medium", "high"]
    steps: list[PreparedStep]


class JudgeConfig(StrictModel):
    model: str = Field(min_length=1)
    thinking_level: Literal["off", "low", "medium", "high"]
    prompt: str = Field(min_length=1)
