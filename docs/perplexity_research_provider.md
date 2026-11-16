# TAK SCOUT Perplexity Research Provider

## Purpose

`PerplexityResearchProvider` adds a separate web-research adapter to TAK SCOUT. It does not replace RSS collection, interview generation, or the existing content rewrite provider.

The provider returns:
- `query`: the submitted research question
- `answer`: Perplexity's answer text
- `citations`: unique HTTP(S) source URLs returned by the API
- `model`: the model reported by the API (or the configured model)

## Configuration

Set these environment variables in the runtime environment. Do not commit API keys to Git.

| Variable | Required | Default |
|---|---:|---|
| `TAK_SCOUT_PERPLEXITY_API_KEY` | Yes | — |
| `TAK_SCOUT_PERPLEXITY_MODEL` | No | `sonar-pro` |
| `TAK_SCOUT_PERPLEXITY_ENDPOINT` | No | `https://api.perplexity.ai/chat/completions` |

The endpoint must use HTTPS.

## Python usage

```python
from tak_scout import PerplexityResearchProvider

provider = PerplexityResearchProvider.from_environment()
result = provider.search(
    "2026년 국내 부동산 경매 제도 변경사항",
    search_recency_filter="month",
)

print(result.answer)
for url in result.citations:
    print(url)
```

Optional search controls:
- `search_recency_filter`: `day`, `week`, `month`, or `year`
- `search_domain_filter`: tuple of hostnames, such as `("law.go.kr", "court.go.kr")`

## Safety and behavior

- No API request occurs when the provider is constructed.
- The API key is read from the environment and sent only in the Authorization header.
- Empty queries and invalid search filters are rejected before the request.
- Only HTTP(S) citation URLs are returned; duplicate URLs are removed.
- HTTP, timeout, and malformed-response failures raise `LLMResponseError`.
- The provider does not publish content, approve KNOWLEDGE, or modify RSS/SCOUT records.
- Research output is a draft for human verification. Check each cited source and its publication date before using legal, financial, or policy claims in public content.

## Tests

Run the focused tests:

```bash
python3 -m unittest tests.test_perplexity_research -v
```

Run the full suite:

```bash
python3 -m unittest discover -s tests -p 'test*.py' -v
```
