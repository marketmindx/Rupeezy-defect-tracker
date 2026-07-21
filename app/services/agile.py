"""Sprint / Story / Epic management with audit logging.

Same conventions as the defect service: services validate, stage audit rows
through :class:`ActivityService`, and own the commit.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from app.exceptions import ConflictError, ValidationError
from app.extensions import db
from app.models import (
    ActivityAction,
    DefectStatus,
    Epic,
    Sprint,
    SprintStatus,
    Story,
    StoryStatus,
    User,
)
from app.repositories.agile import EpicRepository, SprintRepository, StoryRepository
from app.services.activity import ActivityService
from app.services.base import BaseService
from app.services.keys import next_key


class SprintService(BaseService):
    def __init__(
        self,
        repository: Optional[SprintRepository] = None,
        activity: Optional[ActivityService] = None,
    ) -> None:
        self.repository = repository or SprintRepository()
        self.activity = activity or ActivityService()

    # -- queries -----------------------------------------------------------
    def get(self, sprint_id: int) -> Sprint:
        return self.repository.get_or_raise(sprint_id)

    def list_overview(self) -> "List[Dict[str, Any]]":
        return [
            {
                "sprint": sprint,
                "total": total,
                "done": done,
                "stories": stories,
                "pct": round(done * 100 / total) if total else 0,
            }
            for sprint, total, done, stories in self.repository.list_with_rollups()
        ]

    def detail_context(self, sprint_id: int) -> "Dict[str, Any]":
        sprint = self.repository.get_or_raise(sprint_id)
        total, done = self.repository.stats(sprint_id)
        return {
            "sprint": sprint,
            "total": total,
            "done": done,
            "open_count": total - done,
            "pct": round(done * 100 / total) if total else 0,
            "days_left": max((sprint.end_date - date.today()).days, 0),
            "breakdown": self.repository.status_breakdown(sprint_id),
            "stories": StoryRepository().for_sprint_with_counts(sprint_id),
            "defects": self.repository.defects_for(sprint_id),
            "statuses": list(DefectStatus),
        }

    # -- mutations -----------------------------------------------------------
    def create_sprint(
        self,
        *,
        actor: User,
        name: str,
        number: int,
        goal: Optional[str],
        start_date: date,
        end_date: date,
        status: SprintStatus,
    ) -> Sprint:
        self._validate(number=number, start=start_date, end=end_date)
        sprint = Sprint(
            name=name.strip(),
            number=number,
            goal=(goal or "").strip() or None,
            start_date=start_date,
            end_date=end_date,
            status=status,
        )
        self.repository.add(sprint)
        self.repository.flush()
        self.activity.log(
            entity_type="sprint", entity_id=sprint.id, actor=actor,
            action=ActivityAction.CREATED, new_value=sprint.name,
        )
        self.commit()
        return sprint

    def update_sprint(
        self,
        *,
        actor: User,
        sprint_id: int,
        name: str,
        number: int,
        goal: Optional[str],
        start_date: date,
        end_date: date,
        status: SprintStatus,
    ) -> Sprint:
        sprint = self.repository.get_or_raise(sprint_id)
        self._validate(number=number, start=start_date, end=end_date, exclude_id=sprint.id)

        changes: "Dict[str, tuple]" = {}

        def scalar(field: str, new_value, display=str) -> None:
            old_value = getattr(sprint, field)
            if old_value != new_value:
                changes[field] = (
                    None if old_value is None else display(old_value),
                    None if new_value is None else display(new_value),
                )
                setattr(sprint, field, new_value)

        scalar("name", name.strip())
        scalar("number", number)
        scalar("goal", (goal or "").strip() or None)
        scalar("start_date", start_date, lambda value: value.isoformat())
        scalar("end_date", end_date, lambda value: value.isoformat())
        scalar("status", status, lambda value: value.value)

        if changes:
            self.activity.log_field_changes(
                entity_type="sprint", entity_id=sprint.id, actor=actor, changes=changes
            )
            self.commit()
        return sprint

    def _validate(
        self, *, number: int, start: date, end: date, exclude_id: Optional[int] = None
    ) -> None:
        if end < start:
            raise ValidationError("End date must be on or after the start date.")
        if self.repository.number_taken(number, exclude_id=exclude_id):
            raise ConflictError(f"Sprint number {number} already exists.")


class StoryService(BaseService):
    def __init__(
        self,
        repository: Optional[StoryRepository] = None,
        activity: Optional[ActivityService] = None,
    ) -> None:
        self.repository = repository or StoryRepository()
        self.activity = activity or ActivityService()

    def get(self, story_id: int) -> Story:
        return self.repository.get_or_raise(story_id)

    def tree(self) -> "List[dict]":
        groups = self.repository.tree_groups()
        for group in groups:
            group["defect_count"] = sum(len(defects) for _, defects in group["stories"])
        return groups

    def create_story(
        self,
        *,
        actor: User,
        title: str,
        description: Optional[str],
        epic_id: Optional[int],
        sprint_id: Optional[int],
        status: StoryStatus,
        story_points: Optional[int],
    ) -> Story:
        self._validate_links(epic_id, sprint_id)
        story = Story(
            key=next_key("story"),
            title=title.strip(),
            description=(description or "").strip() or None,
            epic_id=epic_id,
            sprint_id=sprint_id,
            status=status,
            story_points=story_points,
        )
        self.repository.add(story)
        self.repository.flush()
        self.activity.log(
            entity_type="story", entity_id=story.id, actor=actor,
            action=ActivityAction.CREATED, new_value=story.key,
        )
        self.commit()
        return story

    def update_story(
        self,
        *,
        actor: User,
        story_id: int,
        title: str,
        description: Optional[str],
        epic_id: Optional[int],
        sprint_id: Optional[int],
        status: StoryStatus,
        story_points: Optional[int],
    ) -> Story:
        story = self.repository.get_or_raise(story_id)
        self._validate_links(epic_id, sprint_id)

        changes: "Dict[str, tuple]" = {}

        def scalar(field: str, new_value, display=str) -> None:
            old_value = getattr(story, field)
            if old_value != new_value:
                changes[field] = (
                    None if old_value is None else display(old_value),
                    None if new_value is None else display(new_value),
                )
                setattr(story, field, new_value)

        scalar("title", title.strip())
        scalar("description", (description or "").strip() or None)
        scalar("status", status, lambda value: value.value)
        scalar("story_points", story_points)

        if epic_id != story.epic_id:
            old_epic = db.session.get(Epic, story.epic_id) if story.epic_id else None
            new_epic = db.session.get(Epic, epic_id) if epic_id else None
            changes["epic"] = (
                old_epic.key if old_epic else None,
                new_epic.key if new_epic else None,
            )
            story.epic_id = epic_id
        if sprint_id != story.sprint_id:
            old_sprint = db.session.get(Sprint, story.sprint_id) if story.sprint_id else None
            new_sprint = db.session.get(Sprint, sprint_id) if sprint_id else None
            changes["sprint"] = (
                old_sprint.name if old_sprint else None,
                new_sprint.name if new_sprint else None,
            )
            story.sprint_id = sprint_id

        if changes:
            self.activity.log_field_changes(
                entity_type="story", entity_id=story.id, actor=actor, changes=changes
            )
            self.commit()
        return story

    @staticmethod
    def _validate_links(epic_id: Optional[int], sprint_id: Optional[int]) -> None:
        if epic_id and db.session.get(Epic, epic_id) is None:
            raise ValidationError("Choose a valid epic.")
        if sprint_id and db.session.get(Sprint, sprint_id) is None:
            raise ValidationError("Choose a valid sprint.")


class EpicService(BaseService):
    def __init__(
        self,
        repository: Optional[EpicRepository] = None,
        activity: Optional[ActivityService] = None,
    ) -> None:
        self.repository = repository or EpicRepository()
        self.activity = activity or ActivityService()

    def get(self, epic_id: int) -> Epic:
        return self.repository.get_or_raise(epic_id)

    def create_epic(self, *, actor: User, name: str, description: Optional[str]) -> Epic:
        epic = Epic(
            key=next_key("epic"),
            name=name.strip(),
            description=(description or "").strip() or None,
        )
        self.repository.add(epic)
        self.repository.flush()
        self.activity.log(
            entity_type="epic", entity_id=epic.id, actor=actor,
            action=ActivityAction.CREATED, new_value=epic.key,
        )
        self.commit()
        return epic

    def update_epic(
        self, *, actor: User, epic_id: int, name: str, description: Optional[str]
    ) -> Epic:
        epic = self.repository.get_or_raise(epic_id)
        changes: "Dict[str, tuple]" = {}
        new_name = name.strip()
        new_description = (description or "").strip() or None
        if new_name != epic.name:
            changes["name"] = (epic.name, new_name)
            epic.name = new_name
        if new_description != epic.description:
            changes["description"] = (epic.description, new_description)
            epic.description = new_description
        if changes:
            self.activity.log_field_changes(
                entity_type="epic", entity_id=epic.id, actor=actor, changes=changes
            )
            self.commit()
        return epic
