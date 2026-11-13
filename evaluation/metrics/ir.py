"""Reference-based retrieval metrics against human-labelled gold chunk ids (no LLM judge, no cost)."""
import math


def hit_at_k(ranked, gold, k):
    return float(bool(set(ranked[:k]) & set(gold)))


def recall_at_k(ranked, gold, k):
    return len(set(ranked[:k]) & set(gold)) / len(set(gold)) if gold else None


def precision_at_k(ranked, gold, k):
    top = ranked[:k]
    return len(set(top) & set(gold)) / len(top) if top else 0.0


def mrr(ranked, gold):
    return next((1 / rank for rank, chunk in enumerate(ranked, 1) if chunk in set(gold)), 0.0)


def ndcg_at_k(ranked, gold, k):
    gold = set(gold)
    dcg = sum(1 / math.log2(rank + 1) for rank, chunk in enumerate(ranked[:k], 1) if chunk in gold)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(gold), k) + 1))
    return dcg / ideal if ideal else None


def score_ranking(ranked, gold, k):
    """All metrics for one ranked list of chunk ids. Empty gold (unanswerable) returns None."""
    if not gold:
        return None
    return {'hit': hit_at_k(ranked, gold, k), 'recall': recall_at_k(ranked, gold, k),
            'precision': precision_at_k(ranked, gold, k), 'mrr': mrr(ranked[:k], gold),
            'ndcg': ndcg_at_k(ranked, gold, k), 'returned': len(ranked[:k])}


def mean_scores(rows):
    rows = [r for r in rows if r is not None]
    if not rows:
        return {'n': 0}
    keys = [k for k in rows[0] if k != 'returned']
    return {'n': len(rows), **{k: sum(r[k] for r in rows) / len(rows) for k in keys}}


def ranks_to_list(ranks):
    """{'chunk_id': rank} as stored in the app's retrieval info -> ordered chunk ids."""
    return [chunk for chunk, _ in sorted(ranks.items(), key=lambda item: item[1])]
