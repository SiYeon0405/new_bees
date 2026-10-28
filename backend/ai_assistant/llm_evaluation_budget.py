"""Conservative reservation ledger for a separately approved LLM evaluation.

The caller must supply an exact provider input-token count for the identical
request. Local byte length is never accepted as a token count.
"""
from decimal import Decimal

MAX_REQUESTS = 6
MAX_REQUEST_BYTES = 3000
MAX_OUTPUT_TOKENS = 200
MAX_COST_NANODOLLARS = 5_000_000  # $0.005
INPUT_NANODOLLARS_PER_TOKEN = 150  # $0.15 / million
OUTPUT_NANODOLLARS_PER_TOKEN = 600  # $0.60 / million


class EvaluationBudgetError(Exception):
    pass


def maximum_request_cost(input_tokens, output_tokens):
    if type(input_tokens) is not int or input_tokens < 0:
        raise EvaluationBudgetError('trusted_input_token_count_required')
    if type(output_tokens) is not int or not 0 < output_tokens <= MAX_OUTPUT_TOKENS:
        raise EvaluationBudgetError('invalid_output_limit')
    return input_tokens * INPUT_NANODOLLARS_PER_TOKEN + output_tokens * OUTPUT_NANODOLLARS_PER_TOKEN


def reserve_next(ledger, *, exact_input_tokens, payload_bytes, output_tokens=MAX_OUTPUT_TOKENS):
    if type(payload_bytes) is not int or payload_bytes > MAX_REQUEST_BYTES or payload_bytes < 1:
        raise EvaluationBudgetError('request_payload_too_large')
    cost = maximum_request_cost(exact_input_tokens, output_tokens)
    accepted = ledger.eval('''
        local requests = tonumber(redis.call('GET', KEYS[1]) or '0')
        local reserved = tonumber(redis.call('GET', KEYS[2]) or '0')
        if requests + 1 > 6 or reserved + tonumber(ARGV[1]) > 5000000 then return 0 end
        redis.call('INCR', KEYS[1])
        redis.call('INCRBY', KEYS[2], ARGV[1])
        return 1
    ''', 2, 'bees:llm_eval:requests', 'bees:llm_eval:reserved_nano', cost)
    if accepted != 1:
        raise EvaluationBudgetError('approved_budget_exceeded')
    return cost


def dollars(nanodollars):
    return Decimal(nanodollars) / Decimal(1_000_000_000)
