from fastapi import APIRouter, Depends, HTTPException

from auth.dependencies import require_scope
from models.schemas import ShortcutRunRequest
from services.shortcuts import ShortcutsRunner

router = APIRouter(tags=["shortcuts"])


@router.post("/v1/shortcuts/run")
async def run_shortcut(
    body: ShortcutRunRequest,
    _key=Depends(require_scope("shortcuts:run")),
):
    result = ShortcutsRunner().run(body.name, input_text=body.input, timeout=body.timeout_seconds)
    if result.status == "cli_missing":
        raise HTTPException(status_code=503, detail="shortcuts_cli_missing")
    return {
        "status": result.status,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
