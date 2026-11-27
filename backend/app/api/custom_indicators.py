"""CRUD for formula-based custom indicators. Values are served by GET /indicators/custom-<id>."""
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import SessionDep
from app.indicators.formula import FormulaError, InputDef, PlotDef, Program
from app.indicators.registry import Indicator, Param, Plot
from app.models import CustomIndicator
from app.auth.deps import UserDep

router = APIRouter(prefix="/custom-indicators", tags=["indicators"])
PREFIX = "custom-"


class InputIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    default: float
    min: float = 1
    max: float = 1000


class PlotIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    expr: str = Field(min_length=1, max_length=500)
    style: str = "line"
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")


class CustomIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    overlay: bool = False
    inputs: list[InputIn] = []
    plots: list[PlotIn]
    levels: list[float] = Field([], max_length=5)


class CustomOut(CustomIn):
    id: str          # "custom-<n>", the id used with /indicators/{id}
    warmup: int


def build_program(inputs: list[dict], plots: list[dict]) -> Program:
    return Program([InputDef(i["name"], i["default"], i.get("min", 1), i.get("max", 1000)) for i in inputs],
                   [PlotDef(p["name"], p["expr"], p.get("style", "line"), p.get("color")) for p in plots])


def _compile(body: CustomIn) -> Program:
    try:
        return build_program([i.model_dump() for i in body.inputs], [p.model_dump() for p in body.plots])
    except FormulaError as e:
        raise HTTPException(400, {"message": str(e), "plot": e.plot, "col": e.col}) from None


def to_indicator(row: CustomIndicator) -> Indicator:
    prog = build_program(row.inputs_json, row.plots_json)
    return Indicator(
        id=f"{PREFIX}{row.id}", title=row.name, category="Custom", overlay=row.overlay,
        plots=tuple(Plot(p["name"], p.get("style", "line"), p.get("color")) for p in row.plots_json),
        params=tuple(Param(i["name"], i["default"], i.get("min", 1), i.get("max", 1000), "float")
                     for i in row.inputs_json),
        fn=lambda bars, **params: prog.run(bars, params),
        warmup=prog.warmup,
        levels=tuple(row.levels_json or ()),
    )


def user_customs(session: Session, uid: int) -> list[CustomIndicator]:
    return list(session.scalars(select(CustomIndicator).where(CustomIndicator.user_id == uid)
                                .order_by(CustomIndicator.id)))


def get_custom(session: Session, ind_id: str, uid: int) -> CustomIndicator:
    try:
        row = session.get(CustomIndicator, int(ind_id.removeprefix(PREFIX)))
    except ValueError:
        row = None
    if row is None or row.user_id != uid:
        raise HTTPException(404, f"custom indicator {ind_id} not found")
    return row


def _out(row: CustomIndicator) -> CustomOut:
    prog = build_program(row.inputs_json, row.plots_json)
    return CustomOut(id=f"{PREFIX}{row.id}", name=row.name, overlay=row.overlay, inputs=row.inputs_json,
                     plots=row.plots_json, levels=row.levels_json or [],
                     warmup=prog.warmup({i["name"]: i["default"] for i in row.inputs_json}))


def _apply(row: CustomIndicator, body: CustomIn) -> None:
    row.name, row.overlay = body.name.strip(), body.overlay
    row.inputs_json = [i.model_dump() for i in body.inputs]
    row.plots_json = [p.model_dump() for p in body.plots]
    row.levels_json = list(body.levels)
    row.updated_at = time.time()


@router.get("", response_model=list[CustomOut])
def list_custom(user: UserDep, session: SessionDep) -> list[CustomOut]:
    return [_out(r) for r in user_customs(session, user.id)]


@router.post("/check")
def check(body: CustomIn) -> JSONResponse:
    """Validate a definition without saving it."""
    prog = _compile(body)
    return JSONResponse({"ok": True, "warmup": prog.warmup({i.name: i.default for i in body.inputs})})


@router.post("", response_model=CustomOut, status_code=201)
def create(user: UserDep, body: CustomIn, session: SessionDep) -> CustomOut:
    _compile(body)
    row = CustomIndicator(user_id=user.id)
    _apply(row, body)
    session.add(row)
    session.commit()
    return _out(row)


@router.put("/{ind_id}", response_model=CustomOut)
def update(user: UserDep, ind_id: str, body: CustomIn, session: SessionDep) -> CustomOut:
    row = get_custom(session, ind_id, user.id)
    _compile(body)
    _apply(row, body)
    session.commit()
    return _out(row)


@router.delete("/{ind_id}", status_code=204)
def delete(user: UserDep, ind_id: str, session: SessionDep) -> None:
    row = get_custom(session, ind_id, user.id)
    session.delete(row)
    session.commit()
