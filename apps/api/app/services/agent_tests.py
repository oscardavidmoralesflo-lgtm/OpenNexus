"""The quality lab: ask an agent its test questions and grade the answers.

Each test case is a question and, in plain words, what a good answer must do.
A run asks the agent the question with its current instructions and
knowledge, the way the playground does, then a second call grades the answer
against the expectation and the knowledge the agent was given.

Tests answer without the agent's tools: an HTTP or MCP tool can change
something outside Agentaria (book a slot, write to a CRM), and a test must
never do that.
"""

from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from ..models import Agent, AgentTestCase, now_utc
from .ai import chat_completion
from .knowledge import build_system_prompt, retrieve_knowledge
from .usage import record_usage

PASS_SCORE = 70

JUDGE_PROMPT = """You review answers given by a customer service AI agent.
You get the customer's question, what a good answer must do, the business
information the agent had, and the agent's answer.

Score the answer from 0 to 100:
- It must meet the expectation. When the expectation is empty, judge whether
  the answer is correct, helpful and polite for that business.
- Any fact not supported by the business information (a price, a schedule,
  a policy) is invented: score it 40 or less.
- Ignore style and length unless the expectation mentions them.

Reply with JSON only: {"score": <0-100>, "reason": "<one sentence>"}.
Write the reason in the language of the question."""


def _parse_verdict(text: str) -> tuple[int, str]:
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        data = json.loads(match.group(0))
        score = int(data["score"])
        reason = str(data.get("reason", "")).strip()
    except (ValueError, TypeError, AttributeError, KeyError):
        return 0, "The grader returned an answer that could not be read."
    return max(0, min(100, score)), reason[:500]


async def run_case(db: Session, agent: Agent, credentials: tuple[str, str], case: AgentTestCase) -> AgentTestCase:
    """Answer and grade one case, storing the verdict on it. The caller commits."""
    base_url, api_key = credentials
    model = agent.model.strip()
    knowledge = await retrieve_knowledge(db, agent, case.question)
    system = build_system_prompt(agent, knowledge.text)
    answer = await chat_completion(
        agent.provider, base_url, api_key, model,
        [{"role": "system", "content": system}, {"role": "user", "content": case.question}],
        temperature=agent.temperature, max_tokens=agent.max_tokens,
    )
    record_usage(db, agent.agency_id, agent.id, agent.provider, model, answer, purpose="test")

    review = (
        f"Question:\n{case.question}\n\nExpectation:\n{case.expectation or '(none)'}\n\n"
        f"Business information:\n{knowledge.text or '(none)'}\n\nAgent's answer:\n{answer.text}"
    )
    verdict = await chat_completion(
        agent.provider, base_url, api_key, model,
        [{"role": "system", "content": JUDGE_PROMPT}, {"role": "user", "content": review}],
        temperature=0, max_tokens=300,
    )
    record_usage(db, agent.agency_id, agent.id, agent.provider, model, verdict, purpose="test")
    score, reason = _parse_verdict(verdict.text)

    case.last_answer = answer.text
    case.last_score = score
    case.last_passed = score >= PASS_SCORE
    case.last_reason = reason
    case.last_run_at = now_utc()
    return case
