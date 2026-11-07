"""Routers for the Past / Present / Future / Review workflows. Each workflow owns its own module:
gondola/api/tri_past.py, tri_present.py, tri_future.py, tri_review.py, each exposing `router`."""
from fastapi import APIRouter

router = APIRouter()
for _name in ("tri_past", "tri_present", "tri_future", "tri_review"):
    try:
        _mod = __import__(f"gondola.api.{_name}", fromlist=["router"])
        router.include_router(_mod.router)
    except ModuleNotFoundError as e:  # module not written yet
        if _name not in str(e):
            raise
