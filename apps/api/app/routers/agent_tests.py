"""The quality lab: test questions per agent, and runs that grade the answers."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Agent, AgentTestCase, User
from ..services.agent_tests import PASS_SCORE, run_case
from ..services.providers import resolve_agent_credentials

router = APIRouter(prefix="/agents", tags=["Agent quality"])

MAX_CASES = 50


class TestCaseIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    expectation: str = Field(default="", max_length=2000)


class TestCaseUpdate(BaseModel):
    question: str | None = Field(default=None, min_length=2, max_length=2000)
    expectation: str | None = Field(default=None, max_length=2000)


class TestCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    expectation: str
    last_answer: str | None
    last_passed: bool | None
    last_score: int | None
    last_reason: str | None
    last_run_at: datetime | None
    created_at: datetime


class TestSuiteOut(BaseModel):
    cases: list[TestCaseOut]
    pass_score: int
    passed: int
    failed: int
    not_run: int


def _agent(db: Session, user: User, agent_id: uuid.UUID) -> Agent:
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.agency_id == user.agency_id, Agent.deleted_at.is_(None)))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def _cases(db: Session, agent: Agent) -> list[AgentTestCase]:
    return list(db.scalars(select(AgentTestCase).where(AgentTestCase.agent_id == agent.id).order_by(AgentTestCase.created_at)))


def _case(db: Session, agent: Agent, case_id: uuid.UUID) -> AgentTestCase:
    case = db.scalar(select(AgentTestCase).where(AgentTestCase.id == case_id, AgentTestCase.agent_id == agent.id))
    if not case:
        raise HTTPException(status_code=404, detail="Test not found")
    return case


def _suite(cases: list[AgentTestCase]) -> TestSuiteOut:
    return TestSuiteOut(
        cases=cases, pass_score=PASS_SCORE,
        passed=sum(1 for c in cases if c.last_passed is True),
        failed=sum(1 for c in cases if c.last_passed is False),
        not_run=sum(1 for c in cases if c.last_passed is None),
    )


@router.get("/{agent_id}/tests", response_model=TestSuiteOut)
def list_tests(agent_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _suite(_cases(db, _agent(db, user, agent_id)))


@router.post("/{agent_id}/tests", response_model=TestCaseOut, status_code=status.HTTP_201_CREATED)
def create_test(agent_id: uuid.UUID, payload: TestCaseIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    agent = _agent(db, user, agent_id)
    if len(_cases(db, agent)) >= MAX_CASES:
        raise HTTPException(status_code=409, detail=f"An agent can have up to {MAX_CASES} tests")
    case = AgentTestCase(agency_id=agent.agency_id, agent_id=agent.id, question=payload.question.strip(), expectation=payload.expectation.strip())
    db.add(case)
    db.commit()
    return case


@router.patch("/{agent_id}/tests/{case_id}", response_model=TestCaseOut)
def update_test(agent_id: uuid.UUID, case_id: uuid.UUID, payload: TestCaseUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = _case(db, _agent(db, user, agent_id), case_id)
    if payload.question is not None:
        case.question = payload.question.strip()
    if payload.expectation is not None:
        case.expectation = payload.expectation.strip()
    # A changed test has not been run as it now stands.
    case.last_answer = case.last_passed = case.last_score = case.last_reason = case.last_run_at = None
    db.commit()
    return case


@router.delete("/{agent_id}/tests/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_test(agent_id: uuid.UUID, case_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.delete(_case(db, _agent(db, user, agent_id), case_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{agent_id}/tests/run", response_model=TestSuiteOut)
async def run_tests(agent_id: uuid.UUID, case_id: uuid.UUID | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Run every test of the agent, or only ``case_id``, and return the suite."""
    agent = _agent(db, user, agent_id)
    credentials = resolve_agent_credentials(db, agent)
    if not credentials or not agent.model.strip():
        raise HTTPException(status_code=400, detail="This agent is not ready: set its model and add the provider API key in Settings.")
    targets = [_case(db, agent, case_id)] if case_id else _cases(db, agent)
    for case in targets:
        await run_case(db, agent, credentials, case)
        db.commit()
    return _suite(_cases(db, agent))
