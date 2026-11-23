"""
Announcement endpoints for the High School Management System API

Public visitors can read active announcements. Creating, updating, and
deleting announcements (and listing all announcements, including expired
ones) requires a signed-in teacher account.
"""

import logging
import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from pymongo.errors import PyMongoError

from ..database import announcements_collection, teachers_collection

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"]
)


class AnnouncementInput(BaseModel):
    """Payload for creating or updating an announcement"""
    title: str = Field(..., min_length=1, max_length=120)
    message: str = Field(..., min_length=1, max_length=1000)
    start_date: Optional[date] = None
    expiration_date: date

    @model_validator(mode="after")
    def check_date_order(self):
        if self.start_date and self.expiration_date < self.start_date:
            raise ValueError("expiration_date must be on or after start_date")
        return self


def _require_teacher(teacher_username: Optional[str]) -> None:
    """Raise 401 unless the username belongs to a known teacher account"""
    if not teacher_username:
        raise HTTPException(
            status_code=401, detail="Authentication required for this action")

    try:
        teacher = teachers_collection.find_one({"_id": teacher_username})
    except PyMongoError:
        logger.exception("Failed to verify teacher credentials")
        raise HTTPException(
            status_code=500, detail="Unable to verify credentials. Please try again later.")

    if not teacher:
        raise HTTPException(
            status_code=401, detail="Invalid teacher credentials")


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a stored announcement document into an API response"""
    return {
        "id": doc["_id"],
        "title": doc["title"],
        "message": doc["message"],
        "start_date": doc.get("start_date"),
        "expiration_date": doc["expiration_date"],
    }


def _to_document(payload: AnnouncementInput) -> Dict[str, Any]:
    """Convert a validated payload into a storable document"""
    return {
        "title": payload.title.strip(),
        "message": payload.message.strip(),
        "start_date": payload.start_date.isoformat() if payload.start_date else None,
        "expiration_date": payload.expiration_date.isoformat(),
    }


@router.get("", response_model=List[Dict[str, Any]])
def get_active_announcements() -> List[Dict[str, Any]]:
    """Get announcements that are currently active (started and not expired)"""
    today = date.today().isoformat()
    query = {
        "expiration_date": {"$gte": today},
        "$or": [
            {"start_date": None},
            {"start_date": {"$lte": today}},
        ],
    }

    try:
        docs = announcements_collection.find(query).sort("expiration_date", 1)
        return [_serialize(doc) for doc in docs]
    except PyMongoError:
        logger.exception("Failed to load active announcements")
        raise HTTPException(
            status_code=500, detail="Unable to load announcements.")


@router.get("/manage", response_model=List[Dict[str, Any]])
def get_all_announcements(teacher_username: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """Get all announcements, including scheduled and expired ones - requires teacher authentication"""
    _require_teacher(teacher_username)

    try:
        docs = announcements_collection.find().sort("expiration_date", 1)
        return [_serialize(doc) for doc in docs]
    except PyMongoError:
        logger.exception("Failed to load announcements for management")
        raise HTTPException(
            status_code=500, detail="Unable to load announcements.")


@router.post("", response_model=Dict[str, Any], status_code=201)
def create_announcement(payload: AnnouncementInput, teacher_username: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Create an announcement - requires teacher authentication"""
    _require_teacher(teacher_username)

    doc = {"_id": uuid.uuid4().hex, **_to_document(payload)}
    try:
        announcements_collection.insert_one(doc)
    except PyMongoError:
        logger.exception("Failed to create announcement")
        raise HTTPException(
            status_code=500, detail="Unable to create announcement.")

    return {"message": "Announcement created", "announcement": _serialize(doc)}


@router.put("/{announcement_id}", response_model=Dict[str, Any])
def update_announcement(announcement_id: str, payload: AnnouncementInput, teacher_username: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Update an existing announcement - requires teacher authentication"""
    _require_teacher(teacher_username)

    try:
        result = announcements_collection.find_one_and_update(
            {"_id": announcement_id},
            {"$set": _to_document(payload)},
            return_document=True,
        )
    except PyMongoError:
        logger.exception("Failed to update announcement %s", announcement_id)
        raise HTTPException(
            status_code=500, detail="Unable to update announcement.")

    if not result:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement updated", "announcement": _serialize(result)}


@router.delete("/{announcement_id}", response_model=Dict[str, Any])
def delete_announcement(announcement_id: str, teacher_username: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Delete an announcement - requires teacher authentication"""
    _require_teacher(teacher_username)

    try:
        result = announcements_collection.delete_one({"_id": announcement_id})
    except PyMongoError:
        logger.exception("Failed to delete announcement %s", announcement_id)
        raise HTTPException(
            status_code=500, detail="Unable to delete announcement.")

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement deleted"}
