"""DeepEval test-case construction and metric configuration. Builds only from captured app output."""
from deepeval.metrics import (AnswerRelevancyMetric, ContextualPrecisionMetric, ContextualRecallMetric,
                              ContextualRelevancyMetric, FaithfulnessMetric)
from deepeval.test_case import LLMTestCase

from evaluation import config

_METRIC_CLASSES = {
    'Faithfulness': FaithfulnessMetric,
    'Answer Relevancy': AnswerRelevancyMetric,
    'Contextual Relevancy': ContextualRelevancyMetric,
    'Contextual Precision': ContextualPrecisionMetric,
    'Contextual Recall': ContextualRecallMetric,
}
# Post-rerank retrieval quality = the generation stage's contextual metrics (same input, expected output
# and final top-4 context), so it is not judged twice. Pre-rerank judges the RRF top-12 in fused order.
STAGES = ('generation', 'retrieval_pre_rerank')


def build_metrics(judge, names):
    # eval_mode='llm' pins the documented LLM-as-a-judge path (no hosted "system_one" model).
    return [_METRIC_CLASSES[name](threshold=config.THRESHOLDS[name], model=judge, include_reason=True,
                                  async_mode=True, eval_mode='llm') for name in names]


def eligible(case):
    """DeepEval runs on answerable goldens whose app run produced an answer to judge."""
    return case['golden']['category'] in config.DEEPEVAL_CATEGORIES and case.get('result') is not None


def build_test_case(case, stage):
    """case = one captured record from runners.adapter. Never invents outputs or contexts."""
    golden, result, contexts = case['golden'], case['result'], case['contexts']
    if stage == 'generation':
        retrieval_context = [c['text'] for c in contexts['final']]
    elif stage == 'retrieval_pre_rerank':
        retrieval_context = [c['text'] for c in contexts['fused']]
    else:
        raise ValueError(f'unknown stage {stage!r}')
    # Contextual metrics ignore actual_output; it is still the real answer, never a placeholder.
    actual_output = result['answer']
    if not retrieval_context:
        return None
    return LLMTestCase(input=golden['question'], actual_output=actual_output,
                       expected_output=golden['expected_answer'], retrieval_context=retrieval_context,
                       name=f'{golden["id"]}:{stage}',
                       metadata={'id': golden['id'], 'stage': stage, 'category': golden['category']})


def stage_metric_names(stage):
    return config.GENERATION_METRICS if stage == 'generation' else config.RETRIEVAL_METRICS


SANITY_CASES = (
    # Deliberate controls: a sound judge must score these low. Built from the public-domain source only.
    {'id': 'SANITY-FABRICATED', 'metric': 'Faithfulness',
     'question': 'How many satellites does NASA have observing the Earth system?',
     'answer': 'NASA has 112 satellites observing Earth, most of them launched by the European Space Agency in 1985.',
     'context': ['They might not know that NASA has 23 satellites looking down at our Earth system to help us understand our home planet.']},
    {'id': 'SANITY-OFF-TOPIC', 'metric': 'Answer Relevancy',
     'question': 'What fuels hurricanes according to the speaker?',
     'answer': 'The recipe needs two cups of flour, one egg and a pinch of salt.',
     'context': ['Well all of that heat that’s getting trapped in the oceans and warming the oceans, that’s fuel for hurricanes.']},
    {'id': 'SANITY-IRRELEVANT-CONTEXT', 'metric': 'Contextual Recall',
     'question': 'Which two ice sheets are described as the biggest?',
     'answer': 'Antarctica and Greenland.',
     'expected': 'Antarctica and Greenland are the two biggest ice sheets.',
     'context': ['Methane is about 20 times more potent a greenhouse gas than carbon dioxide.']},
    {'id': 'SANITY-CONTRADICTION', 'metric': 'Faithfulness',
     'question': 'How long does methane last in the atmosphere?',
     'answer': 'Methane lasts for many centuries, far longer than carbon dioxide.',
     'context': ['but the good news is its lifetime in the atmosphere is much shorter, it lasts only around a decade.']},
)


def sanity_test_cases():
    return [(s, LLMTestCase(input=s['question'], actual_output=s['answer'], retrieval_context=s['context'],
                            expected_output=s.get('expected', s['answer']), name=s['id'],
                            metadata={'id': s['id'], 'stage': 'judge_sanity'})) for s in SANITY_CASES]
