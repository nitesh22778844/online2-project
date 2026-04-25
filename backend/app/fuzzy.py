from rapidfuzz import process, fuzz

COMMON_TERMS = [
    "milk", "mango", "bread", "eggs", "rice", "dal", "oil",
    "sugar", "tea", "coffee", "butter", "curd", "paneer",
    "atta", "biscuits", "chocolate", "laptop", "phone",
    "banana", "apple", "onion", "potato", "tomato", "water",
]


def maybe_correct(query: str) -> tuple[str, bool]:
    """Return (corrected_query, was_corrected). Corrects only if score >= 75."""
    match = process.extractOne(query.lower(), COMMON_TERMS, scorer=fuzz.ratio)
    if match and match[1] >= 75 and match[0] != query.lower():
        return match[0], True
    return query, False
