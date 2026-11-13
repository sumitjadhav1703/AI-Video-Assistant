"""Single source of truth for evaluation settings. Edit here, never in production code."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / 'evaluation'
REPORTS_DIR = EVAL_DIR / 'reports'
RAW_DIR = REPORTS_DIR / 'raw'
CACHE_DIR = EVAL_DIR / '.cache'
LEDGER_FILE = REPORTS_DIR / 'judge_ledger.json'

DEEPEVAL_VERSION = '4.3.4'

# Dataset shape: the validator fails if the golden file drifts from this design.
CATEGORY_COUNTS = {
    'direct_factual': 10, 'multi_passage': 6, 'numerical_date': 6, 'named_entity': 5,
    'multi_hop': 5, 'unanswerable': 6, 'ambiguous': 3, 'misleading': 4,
}
CATEGORY_BEHAVIOR = {
    'direct_factual': 'answer', 'multi_passage': 'answer', 'numerical_date': 'answer',
    'named_entity': 'answer', 'multi_hop': 'answer', 'unanswerable': 'abstain',
    'ambiguous': 'answer_or_abstain', 'misleading': 'correct_premise_or_abstain',
}
CATEGORY_PREFIX = {
    'direct_factual': 'F', 'multi_passage': 'M', 'numerical_date': 'N', 'named_entity': 'E',
    'multi_hop': 'H', 'unanswerable': 'U', 'ambiguous': 'A', 'misleading': 'P',
}
# DeepEval reference metrics need an answer to compare against; abstention-style cases are scored
# by the deterministic suite instead (AnswerRelevancy/Recall are undefined for a correct abstention).
DEEPEVAL_CATEGORIES = {c for c, b in CATEGORY_BEHAVIOR.items() if b == 'answer'}

# The app quotes evidence with at least 4 words / 20 characters (backend.core.rag_engine).
MIN_QUOTE_WORDS = 4
MIN_QUOTE_CHARS = 20

# Thresholds: average score is the primary signal, pass rate is secondary (see README).
THRESHOLDS = {
    'Faithfulness': 0.8,          # answers must stay inside the cited transcript quotes
    'Answer Relevancy': 0.7,      # same as the reference suite
    'Contextual Precision': 0.7,  # same as the reference suite
    'Contextual Recall': 0.7,     # same as the reference suite
    'Contextual Relevancy': 0.5,  # statement-level; 500-char chunks carry off-topic sentences by design
}
GENERATION_METRICS = ('Faithfulness', 'Answer Relevancy', 'Contextual Relevancy',
                      'Contextual Precision', 'Contextual Recall')
RETRIEVAL_METRICS = ('Contextual Relevancy', 'Contextual Precision', 'Contextual Recall')

# Meta judge (paid, standard tier: Meta Model API terms 5.1 exclude it from training).
JUDGE_BASE_URL = 'https://api.meta.ai/v1'
JUDGE_MODEL = 'muse-spark-1.3'          # never the "-contributor" variant
JUDGE_REASONING_EFFORT = 'low'
JUDGE_MAX_COMPLETION_TOKENS = 2048
JUDGE_TIMEOUT_SECONDS = 120
# USD per million tokens. Reasoning tokens bill at the output rate. Re-check before each run.
JUDGE_PRICE_INPUT = 1.25
JUDGE_PRICE_OUTPUT = 4.25
PILOT_BUDGET_USD = 0.50
DEFAULT_BUDGET_USD = 10.0

# Hosts the local mode may reach; everything else (Confident AI, PostHog, ...) is refused.
APP_PROVIDER_HOSTS = ('generativelanguage.googleapis.com', 'api.groq.com', 'openrouter.ai',
                      'integrate.api.nvidia.com', 'api.cloudflare.com')
JUDGE_HOSTS = ('api.meta.ai',)
LOOPBACK_HOSTS = ('localhost', '127.0.0.1', '::1')

# Environment forced on the app under test, whatever the developer's .env says.
FORCED_APP_ENV = {
    'ENABLE_PAID_META': 'false',
    'ENABLE_PUBLIC_PAID_FALLBACK': 'false',
    'ENABLE_NVIDIA_PUBLIC': 'false',
    'LANGSMITH_TRACING': 'false',
    'LANGCHAIN_TRACING': 'false',
    'LANGCHAIN_TRACING_V2': 'false',
    # DeepEval: no telemetry, no Confident AI.
    'DEEPEVAL_TELEMETRY_OPT_OUT': 'YES',
    'DEEPEVAL_DISABLE_DOTENV': '1',
    'CONFIDENT_TRACE_FLUSH': 'NO',
    # DeepEval's default ~200 s gather timeout over ALL test cases silently cancelled half a run;
    # the judge client keeps its own per-call timeout (JUDGE_TIMEOUT_SECONDS).
    'DEEPEVAL_DISABLE_TIMEOUTS': '1',
}

# Retrieval cut-offs used for IR metrics: the app keeps 10 dense + 10 sparse, fuses to 12, reranks to 4.
FINAL_K = 4
FUSED_K = 12
