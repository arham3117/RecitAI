"""Tunable values for the whole system.

Spec §4.1. These are reproduced verbatim and are load-bearing: later phases depend on
the exact values. Do not inline any of these anywhere else, and do not quietly lower a
threshold to make a test pass (spec §0.2) — if one is wrong, change it deliberately and
record the change in plan/DECISIONS.md.
"""

# ---- Chunking ----
TARGET_CHUNK_TOKENS = 600
MIN_CHUNK_TOKENS = 120
MAX_CHUNK_TOKENS = 900
CHUNK_OVERLAP_RATIO = 0.15
MIN_CHUNK_TOKENS_FOR_GENERATION = 150

# ---- Embedding ----
EMBEDDING_MODEL = "nomic-embed-text"
EMBEDDING_DIM = 768
EMBEDDING_BATCH_SIZE = 32

# ---- Generation ----
GEN_MODEL = "llama3.1:8b-instruct-q5_K_M"
GEN_TEMPERATURE = 0.7
GEN_MAX_TOKENS = 1024
MAX_REGEN_ATTEMPTS = 2
OPTIONS_PER_QUESTION = 4

# ---- Validator thresholds ----
MAX_CORRECT_LENGTH_RATIO = 1.5      # correct opt vs mean distractor length
MAX_OPTION_SIMILARITY = 0.90        # cosine, between options in one question
MAX_STEM_SIMILARITY = 0.92          # cosine, across questions
DEDUP_LOOKBACK_QUIZZES = 3
BANNED_PHRASES = [
    "all of the above", "none of the above", "both a and b",
    "a and b only", "all of these", "none of these",
]

# ---- Retrieval ----
DEFAULT_TOP_K = 5
RESOLVER_TOP_K = 10
FUZZY_MATCH_THRESHOLD = 85

# ---- Sampler ----
WEAKNESS_MAX_MULTIPLIER = 2.0

# ---- FSRS ----
FSRS_DESIRED_RETENTION = 0.9
