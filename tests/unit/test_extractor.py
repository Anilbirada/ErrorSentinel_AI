from app.errors.extractor import extract_errors
from app.errors.deduplicator import deduplicate
def test_dedupe_tracks_occurrences():
    results=extract_errors("ERR-5021 database connection timeout ERR-5021", "email:test")
    groups=deduplicate(results); assert groups["ERR-5021"]["occurrences"]==2
