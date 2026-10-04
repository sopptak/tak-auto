"""Bridge between the real content production pipeline and the P2-02 AI
Workforce task board (``tak_workforce``).

Why this module exists
-----------------------
P2-02 built an Agent/Tool/Task registry (``tak_workforce``) but it starts
out completely disconnected from the actual SCOUT -> KNOWLEDGE -> MEDIA ->
PUBLISH -> PERFORMANCE pipeline (``content_engine``). Without a bridge the
AI Workforce task board would only ever contain whatever a human manually
types in - it would never reflect what the content factory is really doing.

This module is **read-only** with respect to the content pipeline: it
never mutates ``KnowledgeRecord`` / ``MediaArchiveRecord`` / performance
data, and it never calls ``approve``/``promote``/``publish``. It only
creates ``tak_workforce`` ``Task`` records (via ``tak_workforce.tasks``)
that mirror pipeline items that need attention, so the task board can be
used as a work queue for the agents already defined in the registry.

Idempotency
-----------
Re-running ``sync_pipeline_tasks()`` must never create duplicate tasks for
the same pipeline item. A task is considered "already covered" when an
existing, non-terminal task of the same ``task_type`` already references
the item's id in ``input_refs``. Items that have already moved past the
stage being synced (e.g. a KNOWLEDGE record that was approved/rejected, or
a MEDIA draft that was already promoted/rejected/superseded) are skipped
entirely - the task board should only ever show *actionable* work.

Human-approval safety
----------------------
Publish-preparation tasks are created with ``requested_actions`` such as
``"threads_publish"``/``"youtube_upload"``. ``tak_workforce.tasks.create_task``
already refuses to let those be auto-approved (see
``tak_workforce.registry.HUMAN_APPROVAL_ACTIONS``), so every publish task
this bridge creates lands in ``WAITING_APPROVAL`` - matching the existing
system-wide principle that nothing publishes to a real channel without an
explicit human decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from content_engine.media_archive import MediaArchiveRecord
from tak_brain.models import KnowledgeRecord
from tak_workforce.models import Task
from tak_workforce.tasks import DEFAULT_TASK_PATH, create_task, load_tasks

# task_type values must match tak_workforce.registry.TASK_ROUTES exactly -
# that mapping (not this module) is the single source of truth for which
# agent owns which kind of work.
TASK_TYPE_KNOWLEDGE_REVIEW = "idea_strategy"
TASK_TYPE_BLOG_OR_THREADS_DRAFT = "content_writing"
TASK_TYPE_SHORTS_DRAFT = "shorts_production"
TASK_TYPE_PUBLISH_PREP = "publish_preparation"
TASK_TYPE_PERFORMANCE_ANALYSIS = "performance_analysis"

_PUBLISH_ACTION_BY_PLATFORM = {
    "threads": ("threads_publish",),
    "shorts": ("youtube_upload",),
}

# 6-76 registry: AGENT-01 CEO, AGENT-04 content strategist (idea_strategy),
# AGENT-05 writer (content_writing), AGENT-06 shorts producer
# (shorts_production), AGENT-09 publish ops (publish_preparation),
# AGENT-12 performance analyst (performance_analysis).
_COORDINATOR_AGENT = "AGENT-01"
_IDEA_STRATEGIST_AGENT = "AGENT-04"
_WRITER_AGENT = "AGENT-05"
_SHORTS_PRODUCER_AGENT = "AGENT-06"
_PUBLISH_OPS_AGENT = "AGENT-09"
_PERFORMANCE_AGENT = "AGENT-12"


@dataclass(frozen=True)
class WorkforceSyncResult:
    """Outcome of one ``sync_pipeline_tasks()`` call."""

    created_task_ids: tuple[str, ...] = ()
    skipped_existing_refs: tuple[str, ...] = ()
    skipped_terminal_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_task_ids": list(self.created_task_ids),
            "skipped_existing_refs": list(self.skipped_existing_refs),
            "skipped_terminal_refs": list(self.skipped_terminal_refs),
        }


def _draft_task_type(platform: str) -> str:
    return TASK_TYPE_SHORTS_DRAFT if platform == "shorts" else TASK_TYPE_BLOG_OR_THREADS_DRAFT


def _draft_assignee(platform: str) -> str:
    return _SHORTS_PRODUCER_AGENT if platform == "shorts" else _WRITER_AGENT


def _has_open_task(tasks: list[Task], task_type: str, ref: str) -> bool:
    return any(
        task.task_type == task_type and ref in task.input_refs and task.status not in ("COMPLETED", "CANCELLED")
        for task in tasks
    )


def sync_pipeline_tasks(
    *,
    knowledge_records: tuple[KnowledgeRecord, ...] = (),
    generation_pool_records: tuple[MediaArchiveRecord, ...] = (),
    production_records: tuple[MediaArchiveRecord, ...] = (),
    performance_due_content_ids: tuple[str, ...] = (),
    path: Path | str = DEFAULT_TASK_PATH,
) -> WorkforceSyncResult:
    """Create AI Workforce tasks for pipeline items that need attention.

    Every argument is a tuple of already-loaded records (this function does
    not read any content-pipeline files itself - callers reuse the existing
    loaders, e.g. ``tak_brain.load_knowledge_records`` /
    ``content_engine.media_archive.load_archive`` /
    ``content_engine.performance.schedule.select_due_threads_targets``, the
    same way ``scripts/operator_control_center.py`` already does).
    """
    tasks = list(load_tasks(path))
    created: list[str] = []
    skipped_existing: list[str] = []
    skipped_terminal: list[str] = []

    def _create(task_type: str, *, assigned_to: str, input_refs: tuple[str, ...], requested_actions: tuple[str, ...] = ()) -> None:
        task = create_task(
            task_type,
            created_by=_COORDINATOR_AGENT,
            assigned_to=assigned_to,
            input_refs=input_refs,
            requested_actions=requested_actions,
            path=path,
        )
        tasks.append(task)
        created.append(task.task_id)

    # Stage 1 - KNOWLEDGE awaiting a human review/approval decision needs a
    # content-strategy task so AGENT-04 can prepare the idea for MEDIA.
    for record in knowledge_records:
        ref = record.id
        if record.knowledge_review_status != "pending":
            skipped_terminal.append(f"knowledge:{ref}")
            continue
        if _has_open_task(tasks, TASK_TYPE_KNOWLEDGE_REVIEW, ref):
            skipped_existing.append(f"knowledge:{ref}")
            continue
        _create(TASK_TYPE_KNOWLEDGE_REVIEW, assigned_to=_IDEA_STRATEGIST_AGENT, input_refs=(ref,))

    # Stage 2 - MEDIA generation-pool drafts still unreviewed need a
    # writer/producer task before they can be promoted.
    for record in generation_pool_records:
        ref = record.content_id
        if record.review_status != "unreviewed":
            skipped_terminal.append(f"generation:{ref}")
            continue
        task_type = _draft_task_type(record.platform)
        if _has_open_task(tasks, task_type, ref):
            skipped_existing.append(f"generation:{ref}")
            continue
        _create(task_type, assigned_to=_draft_assignee(record.platform), input_refs=(ref, record.knowledge_id))

    # Stage 3 - approved Production Archive records need publish
    # preparation. These always require human approval (see module docstring).
    for record in production_records:
        ref = record.content_id
        if record.review_status != "approved":
            skipped_terminal.append(f"production:{ref}")
            continue
        if _has_open_task(tasks, TASK_TYPE_PUBLISH_PREP, ref):
            skipped_existing.append(f"production:{ref}")
            continue
        _create(
            TASK_TYPE_PUBLISH_PREP,
            assigned_to=_PUBLISH_OPS_AGENT,
            input_refs=(ref, record.knowledge_id),
            requested_actions=_PUBLISH_ACTION_BY_PLATFORM.get(record.platform, ()),
        )

    # Stage 4 - content_ids whose 24h/72h performance window is due need an
    # analysis task. Callers compute due ids with the existing scheduler
    # (``content_engine.performance.schedule.select_due_threads_targets``).
    for ref in performance_due_content_ids:
        if _has_open_task(tasks, TASK_TYPE_PERFORMANCE_ANALYSIS, ref):
            skipped_existing.append(f"performance:{ref}")
            continue
        _create(TASK_TYPE_PERFORMANCE_ANALYSIS, assigned_to=_PERFORMANCE_AGENT, input_refs=(ref,))

    return WorkforceSyncResult(tuple(created), tuple(skipped_existing), tuple(skipped_terminal))
