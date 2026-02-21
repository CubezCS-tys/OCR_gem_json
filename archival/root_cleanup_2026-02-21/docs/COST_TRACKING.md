# Cost Tracking Guide

## 📊 How Costs Are Calculated

### Pricing (Gemini 2.5 Flash - as of January 2026)

Source: https://ai.google.dev/pricing

| Token Type | Cost per 1M Tokens |
|------------|-------------------|
| Input (text/image/video) | $0.50 |
| Output (including thinking) | $3.00 |
| Context caching | $0.05 |

### Automatic Cost Tracking

The system **automatically tracks costs** for every PDF processed:

1. **During Processing**: Token usage is captured from Gemini API responses
2. **Cost Calculation**: Computed using actual token counts (not estimates)
3. **Stored in Results**: Cost info saved with each job
4. **Cached**: Cost data persists in Redis for 7 days

## 🔍 Checking Individual Job Costs

### After Submitting a Job

```bash
# Submit PDF and get task ID
python submit_jobs.py pdfs/document.pdf

# Output:
# ✓ Submitted: Task abc123-def456...

# Check status and cost
python submit_jobs.py --status abc123-def456-ghi789
```

**Example Output:**
```
State: SUCCESS
Ready: True

✓ Success!
  HTML: ./document.html
  JSON: ./document.json
  Pages: 35
  Time: 42.3s
  Cost: $0.087500
    Input: 52,431 tokens ($0.026215)
    Output: 20,428 tokens ($0.061284)
```

## 📈 Viewing Overall Statistics

### Using Monitor CLI

```bash
# Show processing statistics with costs
python monitor.py --stats
```

**Example Output:**
```
================================================================================
Processing Statistics
================================================================================

📦 Cached Results: 15

Recent Processing Jobs:
+------------------+-------+----------+--------------+---------+
| PDF Hash         | Pages | Time (s) | Cost ($)     | Age     |
+------------------+-------+----------+--------------+---------+
| a1b2c3d4e5f6... | 35    | 42.3     | $0.087500    | 2h ago  |
| 1a2b3c4d5e6f... | 28    | 35.1     | $0.065420    | 3h ago  |
| f6e5d4c3b2a1... | 42    | 51.8     | $0.103250    | 5h ago  |
+------------------+-------+----------+--------------+---------+

💰 Total Cost (last 10): $0.7845
📄 Total Pages: 315
🔤 Total Tokens: 523,841
💵 Cost per Page: $0.002491
```

## 💰 Cost Estimates

### Before Processing

```bash
# The system shows estimates when starting (in logs)
python submit_jobs.py pdfs/document.pdf

# Worker log will show:
# Cost estimate: $0.0875 USD, ~1500 tokens, ~105 seconds
```

### Typical Costs

| Document Type | Pages | Est. Cost | Actual Range |
|---------------|-------|-----------|--------------|
| Text-heavy (low) | 30 | $0.04-0.06 | $0.035-0.065 |
| Mixed content (medium) | 30 | $0.07-0.10 | $0.065-0.110 |
| Image-heavy (high) | 30 | $0.12-0.18 | $0.110-0.200 |

### Token Usage Patterns

**Per Page Average:**
- Input tokens: 1,000-2,000 tokens
- Output tokens: 400-800 tokens
- **Total: ~1,500 tokens per page**

**Cost per page:**
- Input: ~$0.001 per page
- Output: ~$0.0015 per page
- **Total: ~$0.0025 per page**

## 📊 Cost Tracking in Code

### Accessing Cost Data Programmatically

```python
from submit_jobs import check_task_status

# Check task
status = check_task_status('task-id')

if status['successful']:
    result = status['result']
    cost_info = result.get('cost', {})
    
    print(f"Total cost: ${cost_info['total_cost_usd']:.6f}")
    print(f"Input tokens: {cost_info['input_tokens']:,}")
    print(f"Output tokens: {cost_info['output_tokens']:,}")
    print(f"Total tokens: {cost_info['total_tokens']:,}")
```

### Redis Cache Structure

Cost data is stored in Redis:

```python
{
    "pdf_hash": "abc123...",
    "pages": 35,
    "processing_time": 42.3,
    "cost": {
        "input_tokens": 52431,
        "output_tokens": 20428,
        "total_tokens": 72859,
        "input_cost_usd": 0.026215,
        "output_cost_usd": 0.061284,
        "total_cost_usd": 0.087499
    }
}
```

## 💡 Cost Optimization Tips

### 1. Use Result Caching

```bash
# First run: Full cost
python submit_jobs.py pdfs/document.pdf
# Cost: $0.087500

# Second run: FREE (cached)
python submit_jobs.py pdfs/document.pdf
# Cost: $0.000000 (from cache)
```

### 2. Choose Appropriate Resolution

```bash
# Low resolution (50% cost reduction)
python submit_jobs.py pdfs/doc.pdf --resolution low

# Medium (default, balanced)
python submit_jobs.py pdfs/doc.pdf --resolution medium

# High (2x cost, better quality)
python submit_jobs.py pdfs/doc.pdf --resolution high
```

### 3. Batch Similar Documents

Process documents in batches - cache hits reduce costs:

```bash
# Process directory
python submit_jobs.py --directory ./similar_pdfs

# Output shows cache hits:
# → Submitted: doc1.pdf (Task: abc...)
# ✓ Cached: doc2.pdf (duplicate detected)
# → Submitted: doc3.pdf (Task: def...)
```

### 4. Skip Images for Text-Only

```bash
# Don't extract images (faster, cheaper)
python submit_jobs.py pdfs/textbook.pdf --no-images
```

### 5. Monitor Daily Spending

```bash
# Check total daily costs
python monitor.py --stats

# Set up alerts if cost exceeds threshold
# (implement custom script)
```

## 📉 Daily Budget Planning

### Calculate Maximum Daily Cost

With **10,000 requests/day limit** and **15 pages per request**:

```
Maximum pages: 150,000 pages/day
Average cost: $0.0025 per page
Maximum daily cost: $375/day
```

**Typical daily costs:**
- Conservative (30K pages): ~$75/day
- Moderate (75K pages): ~$188/day
- Aggressive (120K pages): ~$300/day

### Budget by Document Count

| Documents/Day | Pages/Doc | Total Pages | Est. Cost |
|---------------|-----------|-------------|-----------|
| 100 | 30 | 3,000 | $7.50 |
| 500 | 30 | 15,000 | $37.50 |
| 1,000 | 30 | 30,000 | $75.00 |
| 2,000 | 30 | 60,000 | $150.00 |
| 4,000 | 30 | 120,000 | $300.00 |

## 🔧 Where Cost Tracking Happens

### 1. PDF to HTML Script

[pdf_to_html.py](pdf_to_html.py) tracks tokens from Gemini API:

```python
# Token tracking (lines 1235-1237)
self._total_input_tokens = 0
self._total_output_tokens = 0

# Capture usage (line 1488)
if hasattr(response, 'usage_metadata'):
    self._total_input_tokens += response.usage_metadata.prompt_token_count
    self._total_output_tokens += response.usage_metadata.candidates_token_count

# Return in result (lines 1858-1865)
result["usage_metadata"] = {
    "total_input_tokens": self._total_input_tokens,
    "total_output_tokens": self._total_output_tokens,
    "total_tokens": self._total_input_tokens + self._total_output_tokens
}
```

### 2. Celery Tasks

[tasks.py](tasks.py) calculates costs:

```python
# Pricing constants (lines 14-15)
GEMINI_INPUT_COST_PER_1M = 0.50
GEMINI_OUTPUT_COST_PER_1M = 3.00

# Calculate cost (lines 21-42)
def calculate_cost(input_tokens, output_tokens):
    input_cost = (input_tokens / 1_000_000) * GEMINI_INPUT_COST_PER_1M
    output_cost = (output_tokens / 1_000_000) * GEMINI_OUTPUT_COST_PER_1M
    return {'total_cost_usd': input_cost + output_cost, ...}

# Add to result (lines 214-220)
if 'usage_metadata' in result:
    cost_info = calculate_cost(...)
    result['cost'] = cost_info
```

### 3. Submit Jobs CLI

[submit_jobs.py](submit_jobs.py) displays costs:

```python
# Show cost when checking status (lines 326-329)
if 'cost' in result:
    cost = result['cost']
    print(f"  Cost: ${cost['total_cost_usd']:.6f}")
    print(f"    Input: {cost['input_tokens']:,} tokens")
```

### 4. Monitor CLI

[monitor.py](monitor.py) aggregates costs:

```python
# Show statistics (lines 237-259)
total_cost = 0
for job in jobs:
    total_cost += job['cost']['total_cost_usd']

print(f"💰 Total Cost: ${total_cost:.4f}")
print(f"💵 Cost per Page: ${total_cost / total_pages:.6f}")
```

## 🎯 Summary

### Cost Information Sources

1. **Gemini API Pricing**: https://ai.google.dev/pricing
2. **Task Status**: `python submit_jobs.py --status <task_id>`
3. **Statistics Dashboard**: `python monitor.py --stats`
4. **Flower Web UI**: http://localhost:5555 (after `celery -A celery_config flower`)
5. **Redis Cache**: Raw cost data stored in Redis

### Key Metrics

- **Current pricing**: $0.50/1M input + $3.00/1M output
- **Average cost**: ~$0.0025 per page
- **Daily limit**: 10,000 requests = 150,000 pages = ~$375 max
- **Typical costs**: $0.03-0.10 per 30-page document

### Optimization Checklist

- ✅ Enable caching (default)
- ✅ Use appropriate resolution
- ✅ Skip images for text-only docs
- ✅ Batch similar documents
- ✅ Monitor daily spending with `monitor.py --stats`
- ✅ Set rate limits to stay under budget
