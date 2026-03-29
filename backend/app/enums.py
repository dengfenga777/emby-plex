from __future__ import annotations

from enum import Enum


class UserRole(str, Enum):
    user = "user"
    admin = "admin"


class MediaType(str, Enum):
    movie = "movie"
    series = "series"
    anime = "anime"


class RequestStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    submitted_to_moviepilot = "submitted_to_moviepilot"
    downloading = "downloading"
    organizing = "organizing"
    finished = "finished"
    failed = "failed"

