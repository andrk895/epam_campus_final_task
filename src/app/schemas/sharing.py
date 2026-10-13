"""Schemas for sharing (project memberships)."""

from app.schemas.projects import Participant


class Membership(Participant):
    """A user's membership of a project, returned by ``POST /projects/{project_id}/invite``."""

    project_id: int
