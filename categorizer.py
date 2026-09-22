import logging
import os
import re
import time
from typing import List, Literal, Sequence, Tuple

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

MAJOR_KEYWORDS = {
    "chemical": ["chemical", "chemical engineer", "aspen", "PFD", "process engineering", "process safety", "reactor", "distillation"],
    "mechanical": ["mechanical", "mechanical engineer", "CAD", "manufacturing", "solidworks", "thermodynamics", "HVAC", "turbine", "automotive", "machine design", "fluid dynamics", "heat transfer"],
    "electrical": ["electrical", "electrical engineer", "circuits", "embedded", "electronics", "PCB"],
    "biomedical": ["biomedical", "biomedical engineer", "medical device", "MATLAB", "FDA", "biomechanics"],
    "civil": ["civil", "civil engineer", "AUTOCAD", "stormwater", "structural", "construction", "infrastructure"],
    "industrial": ["industrial", "industrial engineer", "improvement", "root cause", "operations", "supply chain"],
    "computer": ["computer engineering", "embedded systems", "C/C++", "microcontrollers", "RTOS", "firmware", "hardware design", "FPGA"],
    "petroleum": ["petroleum", "petroleum engineer", "drilling", "reservoir", "oil and gas", "upstream", "downstream"],
    "construction management": ["construction management", "estimating", "subcontractor", "scheduling"],
    "CIS": ["CIS", "network administration", "IT Support", "business applications", "systems administration", "information systems"],
    "MIS": ["MIS", "business analyst", "requirements gathering", "systems analysis", "management information"],
    "computer science": ["computer science", "software", "developer", "data structures", "oop", "python", "java", "C++", "software engineering", "API", "programming"],
}

# Short, disambiguating definitions for the LLM path, since several of these
# majors (CIS vs. MIS vs. computer science vs. computer) overlap heavily on
# vocabulary and only differ by discipline convention.
MAJOR_DESCRIPTIONS = {
    "chemical": "Chemical Engineering",
    "mechanical": "Mechanical Engineering",
    "electrical": "Electrical Engineering",
    "biomedical": "Biomedical Engineering",
    "civil": "Civil Engineering",
    "industrial": "Industrial Engineering (process improvement, operations, supply chain)",
    "computer": "Computer Engineering (hardware-focused: embedded systems, firmware, chip/FPGA design)",
    "petroleum": "Petroleum Engineering",
    "construction management": "Construction Management (scheduling, estimating, subcontractors)",
    "CIS": "Computer Information Systems (IT support, network/systems administration)",
    "MIS": "Management Information Systems (business analyst, systems analysis, requirements gathering)",
    "computer science": "Computer Science / Software Engineering (software development, programming)",
}

# Pre-compile a word-boundary regex per keyword so short/generic keywords
# (e.g. "MIS", "API", "CIS") only match whole words, not substrings inside
# unrelated words like "admission" or "rapids". \b itself only fires at a
# word/non-word transition, which fails right after symbol-ending keywords
# like "C++", so lookarounds on \w are used instead.
_MAJOR_PATTERNS = {
    major: [re.compile(r"(?<!\w)" + re.escape(keyword.lower()) + r"(?!\w)") for keyword in keywords]
    for major, keywords in MAJOR_KEYWORDS.items()
}

_MajorName = Literal[tuple(MAJOR_KEYWORDS.keys())]


class _MajorMatch(BaseModel):
    major: _MajorName
    confidence: int = Field(ge=1, le=5)  # 1 (weak fit) - 5 (clear fit)


class _JobCategorization(BaseModel):
    majors: List[_MajorMatch]


class _BatchItem(BaseModel):
    index: int
    majors: List[_MajorMatch]


class _BatchCategorization(BaseModel):
    results: List[_BatchItem]


_SYSTEM_PROMPT = "You categorize internship job postings by engineering/tech major for a university Discord bot. Majors:\n" + "\n".join(
    f"- {name}: {desc}" for name, desc in MAJOR_DESCRIPTIONS.items()
) + (
    "\n\nReturn only majors that are a genuine fit for this specific posting - not every "
    "tangentially related one. If the role doesn't fit any major, return an empty list. "
    "Order by confidence descending."
)

_BATCH_SYSTEM_PROMPT = _SYSTEM_PROMPT + (
    "\n\nYou will receive N numbered postings. Return exactly one result object per "
    "posting, with `index` set to the bracketed number of the posting it describes. "
    "Never omit a posting; return an empty `majors` list if none fit."
)

_LLM_MODEL = "claude-haiku-4-5"
_anthropic_client = None

BATCH_SIZE = 15
_BATCH_DESC_CHARS = 600


def categorize_job_keywords(title: str, description: str = "") -> List[Tuple[str, int]]:
    """Keyword/regex categorizer. Score = number of distinct keywords matched."""
    text = (title + " " + description).lower()

    scored_majors = []
    for major, patterns in _MAJOR_PATTERNS.items():
        score = sum(1 for pattern in patterns if pattern.search(text))
        if score:
            scored_majors.append((major, score))

    scored_majors.sort(key=lambda pair: pair[1], reverse=True)
    return scored_majors


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.Anthropic()
    return _anthropic_client


def categorize_job_llm(title: str, description: str = "") -> List[Tuple[str, int]]:
    """LLM categorizer (Claude Haiku). Score = model confidence, 1-5."""
    client = _get_anthropic_client()
    response = client.messages.parse(
        model=_LLM_MODEL,
        max_tokens=512,
        system=_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Title: {title}\nDescription: {description[:2000]}",
        }],
        output_format=_JobCategorization,
    )
    result = response.parsed_output
    return _scored(result.majors)


def categorize_job(title: str, description: str = "") -> List[Tuple[str, int]]:
    """Categorizes a job by major, ranked by relevance/confidence.

    Uses Claude Haiku when ANTHROPIC_API_KEY is configured (more accurate,
    understands semantics rather than just keyword overlap), falling back to
    the keyword matcher on any API error or when no key is configured.
    """
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            return categorize_job_llm(title, description)
        except Exception as e:
            log.warning("LLM categorization failed (%s), falling back to keyword matching", e)

    return categorize_job_keywords(title, description)


def _scored(majors: List[_MajorMatch]) -> List[Tuple[str, int]]:
    scored_majors = [
        (match.major, match.confidence)
        for match in majors
        if match.major in MAJOR_KEYWORDS
    ]
    scored_majors.sort(key=lambda pair: pair[1], reverse=True)
    return scored_majors


def _align(results: List[_BatchItem], size: int) -> List[List[Tuple[str, int]] | None]:
    """Positionally align batch results by their explicit `index` field.

    Out-of-range indices are dropped, duplicated indices are first-wins, and
    any posting the model never returned a result for is left as None.
    """
    out: List[List[Tuple[str, int]] | None] = [None] * size
    for item in results:
        if 0 <= item.index < size and out[item.index] is None:
            out[item.index] = _scored(item.majors)
    return out


def _format_batch_prompt(chunk: Sequence[Tuple[str, str]]) -> str:
    parts = []
    for i, (title, description) in enumerate(chunk):
        parts.append(f"[{i}]\nTitle: {title}\nDescription: {description[:_BATCH_DESC_CHARS]}")
    return "\n\n".join(parts)


def _categorize_chunk_llm(chunk: Sequence[Tuple[str, str]]) -> List[List[Tuple[str, int]] | None] | None:
    """Attempts one batch LLM call (with one retry) for a chunk of jobs.

    Returns a list the same length as `chunk`, positionally aligned (slots
    may be None), or None if both attempts failed outright.
    """
    client = _get_anthropic_client()
    prompt = _format_batch_prompt(chunk)
    max_tokens = 64 * len(chunk) + 256

    last_error = None
    for attempt in range(2):
        try:
            response = client.messages.parse(
                model=_LLM_MODEL,
                max_tokens=max_tokens,
                system=_BATCH_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                output_format=_BatchCategorization,
            )
            return _align(response.parsed_output.results, len(chunk))
        except Exception as e:
            last_error = e
            log.warning("Batch categorization attempt %d failed (%s)", attempt + 1, e)
            if attempt == 0:
                time.sleep(1)

    log.warning("Batch categorization failed both attempts (%s)", last_error)
    return None


def categorize_jobs(jobs: Sequence[Tuple[str, str]]) -> List[List[Tuple[str, int]]]:
    """Categorizes many (title, description) pairs, prompt-packed in chunks
    of BATCH_SIZE to cut LLM call volume roughly BATCH_SIZE-fold.

    Positionally aligned with `jobs`. Never raises; never returns None in a
    slot — every job gets a (possibly empty) list of (major, score) pairs,
    falling back through per-job LLM categorization and then keyword
    matching as needed.
    """
    if not jobs:
        return []

    if not os.getenv("ANTHROPIC_API_KEY"):
        return [categorize_job_keywords(title, desc) for title, desc in jobs]

    results: List[List[Tuple[str, int]] | None] = [None] * len(jobs)

    for start in range(0, len(jobs), BATCH_SIZE):
        chunk = jobs[start:start + BATCH_SIZE]
        chunk_index = start // BATCH_SIZE
        aligned = _categorize_chunk_llm(chunk)

        none_count = sum(1 for slot in (aligned or []) if slot is None) if aligned is not None else len(chunk)
        misaligned = aligned is None or none_count > len(chunk) / 2

        if misaligned:
            log.warning(
                "Chunk %d discarded (%s), falling back to per-job categorization",
                chunk_index,
                "no result" if aligned is None else f"{none_count}/{len(chunk)} slots missing",
            )
            for i, (title, desc) in enumerate(chunk):
                results[start + i] = categorize_job(title, desc)
            continue

        for i, slot in enumerate(aligned):
            if slot is None:
                title, desc = chunk[i]
                log.warning("Chunk %d slot %d missing, falling back to per-job categorization", chunk_index, i)
                results[start + i] = categorize_job(title, desc)
            else:
                results[start + i] = slot

    # Should be unreachable (every slot is filled above), but keep the
    # invariant airtight against any future refactor.
    for i, slot in enumerate(results):
        if slot is None:
            title, desc = jobs[i]
            results[i] = categorize_job_keywords(title, desc)

    return results
