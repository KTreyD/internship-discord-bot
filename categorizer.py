
MAJOR_KEYWORDS = {
    "chemical": ["chemical", "chemical engineer", "aspen", "PFD", "process engineering", "process safety", "reactor", "distillation"],
    "mechanical": ["mechanical", "mechanical engineer", "CAD", "manufacturing", "solidworks", "thermodynamics"],
    "electrical": ["electrical", "electrical engineer", "circuits", "embedded", "electronics", "PCB"],
    "biomedical": ["biomedical", "biomedical engineer", "medical device", "MATLAB", "FDA", "biomechanics"],
    "civil": ["civil", "civil engineer", "AUTOCAD", "stormwater", "structural", "construction", "infrastructure"],
    "industrial": ["industrial", "industrial engineer", "improvement", "root cause", "operations", "supply chain"],
    "computer": ["embedded systems", "C/C++", "microcontrollers", "RTOS", "firmware"],
    "petroleum": ["petroleum", "petroleum engineer", "drilling", "well", "reservoir", "oil", "gas"],
    "construction management": ["construction management", "estimating", "subcontractor", "scheduling"],
    "CIS": ["CIS", "network administration", "IT Support", "business applications", "systems administration", "information systems"],
    "MIS": ["MIS", "business analyst", "requirements gathering", "systems analysis", "management information"],
    "computer science": ["computer science", "software", "developer", "data structures", "oop", "python", "java", "C++", "software engineering", "API", "programming"],
}

def categorize_job(title,description=""):
    matchingMajors = []
    string1 = (title + " " + description).lower()
    for major in MAJOR_KEYWORDS:
        keywords = MAJOR_KEYWORDS[major]
        for keyword in keywords:
            if keyword in string1:
                matchingMajors.append(major)
                break
    return matchingMajors

if __name__ == "__main__":
    # Test chemical jobs
    result1 = categorize_job("Chemical Engineer Intern", "Entry level position")
    print("Test 1:", result1)
    
    result2 = categorize_job("Chemical Engineering Intern", "")
    print("Test 2:", result2)
    
    result3 = categorize_job("Chemical Engineer - Intern", "")
    print("Test 3:", result3)
