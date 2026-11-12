"""Interactive client using the same durable admission limits as the API."""
import argparse
import uuid

from dotenv import load_dotenv
from . import db
from .jobs import OWNER_EVALUATION_QUESTIONS, run_job
from .core.llm_gateway import operation_scope, get_llm
from .core.vector_store import get_embeddings
from .core.audio_budget import profile_for_language
from .core.reranker import load_ranker
from .core.rag_engine import load_rag_chain, ask_question
from .usage_limits import Settings, client_key, require_provider_calls

load_dotenv()


def run_pipeline(source: str | None, language: str = 'english', *, owner: bool = False, allow_paid: bool = False) -> dict:
    if owner and (source is not None or language != 'english'):
        raise ValueError('Owner evaluation uses only the built-in synthetic transcript.')
    require_provider_calls(sarvam=language.lower() == 'hinglish')
    job_id = uuid.uuid4().hex
    with operation_scope(job_id, owner=owner, allow_paid=allow_paid, local_owner=owner):
        get_llm()
        get_embeddings()
        load_ranker()
    if not owner:
        profile_for_language(language)
    settings = Settings.from_env()
    identity = client_key('127.0.0.1', settings.rate_limit_secret)
    token = db.admit_job(job_id, language, identity, settings)
    run_job(job_id, source, language, reservation_token=token, owner=owner, allow_paid=allow_paid, local_owner=owner)
    result = db.get_job(job_id)
    if not result or result['status'] != 'done':
        raise RuntimeError('Processing failed.')
    return {'job_id': job_id, **result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner-evaluation', action='store_true', help='Use the built-in synthetic transcript and questions.')
    parser.add_argument('--allow-paid', action='store_true', help='Explicitly allow configured paid routes for this owner evaluation.')
    parser.add_argument('--tier', choices=('economy', 'strong'), default='economy', help='Owner evaluation chat tier.')
    args = parser.parse_args()
    if not args.owner_evaluation and (args.allow_paid or args.tier != 'economy'):
        parser.error('--allow-paid and --tier strong require --owner-evaluation')
    source = None
    language = 'english'
    if not args.owner_evaluation:
        source = input('Enter YouTube URL or local file path: ').strip()
        language = input('Language (english/hinglish): ').strip() or 'english'
    result = run_pipeline(source, language, owner=args.owner_evaluation, allow_paid=args.allow_paid)
    for label, key in [('Title', 'title'), ('Summary', 'summary'), ('Action Items', 'action_items'), ('Key Decisions', 'key_decisions'), ('Open Questions', 'open_questions')]:
        print(f'\n{label}: {result[key]}')
    settings = Settings.from_env()
    identity = client_key('127.0.0.1', settings.rate_limit_secret)
    questions = {str(index): question for index, question in enumerate(OWNER_EVALUATION_QUESTIONS, 1)}
    if args.owner_evaluation:
        for index, question in questions.items():
            print(f'{index}. {question}')
    while True:
        prompt = '\nChoose a question number (or exit): ' if args.owner_evaluation else '\nYou (or exit): '
        question = input(prompt).strip()
        if question.lower() in ('exit', 'quit', 'q'):
            break
        if args.owner_evaluation:
            question = questions.get(question)
        if not question:
            continue
        token = db.reserve_chat(result['job_id'], identity, settings)
        try:
            with operation_scope(result['job_id'], owner=args.owner_evaluation, allow_paid=args.allow_paid,
                                 local_owner=args.owner_evaluation):
                answer = ask_question(load_rag_chain(result['job_id'], args.tier), question)
            print(f"\nAssistant: {answer['answer']}")
        finally:
            db.release_slot('chat', token)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Processing failed. Please try again later.') from None
