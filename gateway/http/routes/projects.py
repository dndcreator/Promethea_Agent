from fastapi import APIRouter, Depends, HTTPException, Response

from gateway.public_contracts import Project, ProjectList, ProjectWrite, SessionProjectWrite
from ..dispatcher import get_gateway_server
from ..project_store import ProjectStore
from ..user_manager import user_manager
from .auth import get_current_user_id

router = APIRouter()


def get_project_store() -> ProjectStore:
    return ProjectStore(user_manager.users_dir / "projects.sqlite3")


@router.get("/projects", response_model=ProjectList)
async def list_projects(user_id: str = Depends(get_current_user_id), store: ProjectStore = Depends(get_project_store)):
    return {"projects": store.list(user_id)}


@router.post("/projects", response_model=Project, status_code=201)
async def create_project(body: ProjectWrite, user_id: str = Depends(get_current_user_id), store: ProjectStore = Depends(get_project_store)):
    try:
        return store.create(user_id, body.name)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.patch("/projects/{project_id}", response_model=Project)
async def rename_project(project_id: str, body: ProjectWrite, user_id: str = Depends(get_current_user_id), store: ProjectStore = Depends(get_project_store)):
    try:
        changed = store.rename(user_id, project_id, body.name)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    if not changed:
        raise HTTPException(404, detail="Project not found")
    return next(row for row in store.list(user_id) if row["project_id"] == project_id)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: str, user_id: str = Depends(get_current_user_id), store: ProjectStore = Depends(get_project_store)):
    if not store.delete(user_id, project_id):
        raise HTTPException(404, detail="Project not found")
    return Response(status_code=204)


@router.put("/sessions/{session_id}/project", status_code=204)
async def assign_session(session_id: str, body: SessionProjectWrite, user_id: str = Depends(get_current_user_id), store: ProjectStore = Depends(get_project_store)):
    manager = getattr(get_gateway_server(), "message_manager", None)
    if manager is None:
        raise HTTPException(503, detail="Message manager not initialized")
    if manager.get_session(session_id, user_id=user_id) is None:
        raise HTTPException(404, detail="Session not found")
    try:
        store.assign(user_id, session_id, body.project_id)
    except KeyError as exc:
        raise HTTPException(404, detail="Project not found") from exc
    return Response(status_code=204)
