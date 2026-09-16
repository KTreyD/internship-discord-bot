import os
import re
from typing import List, Literal, Tuple

from pydantic import BaseModel, Field

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


_SYSTEM_PROMPT = "You categorize internship job postings by engineering/tech major for a university Discord bot. Majors:\n" + "\n".join(
    f"- {name}: {desc}" for name, desc in MAJOR_DESCRIPTIONS.items()
) + (
    "\n\nReturn only majors that are a genuine fit for this specific posting - not every "
    "tangentially related one. If the role doesn't fit any major, return an empty list. "
    "Order by confidence descending."
)

_LLM_MODEL = "claude-haiku-4-5"
_anthropic_client = None


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

    scored_majors = [
        (match.major, match.confidence)
        for match in result.majors
        if match.major in MAJOR_KEYWORDS
    ]
    scored_majors.sort(key=lambda pair: pair[1], reverse=True)
    return scored_majors


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
            print(f"⚠️ LLM categorization failed ({e}), falling back to keyword matching")

    return categorize_job_keywords(title, description)


if __name__ == "__main__":
    # Test chemical jobs
    result1 = categorize_job("Chemical Engineer Intern", "Entry level position")
    print("Test 1:", result1)

    result2 = categorize_job("Chemical Engineering Intern", "")
    print("Test 2:", result2)

    result3 = categorize_job("Chemical Engineer - Intern", "")
    print("Test 3:", result3)

    # Word-boundary regression checks: these used to false-positive under
    # naive substring matching.
    result4 = categorize_job("College Admissions Counselor Intern", "")
    print("Test 4 (should be empty, MIS false positive fixed):", result4)

    result5 = categorize_job("Data Rapids Intern", "")
    print("Test 5 (should be empty, API false positive fixed):", result5)
