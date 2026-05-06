# AiMa

## AI Router — Multi-Agent Pipeline

A multi-agent AI system with semantic compression, Redis-backed memory, and OpenRouter LLM integration.

### Architecture

```
user input
   |
[Router Agent]
   |
+------------------------------+
|  Multi-Agent Layer (5 agents)|
|  - planner                   |
|  - coder                     |
|  - analyst                   |
|  - summarizer                |
|  - validator                 |
+------------------------------+
   |
[Semantic Compressor]
   |
[Redis Memory + State]
   |
[OpenRouter + Fallback Chain]
   |
[Batch Queue Optimizer]
   |
response
```

### Project Structure

```
ai-router/
├── core/
│   ├── agents.py       # Multi-agent definitions (planner, coder, analyst, summarizer, validator)
│   ├── batcher.py      # Batch queue optimizer for merging requests
│   ├── compressor.py   # Semantic text compression via LLM
│   ├── llm.py          # OpenRouter API wrapper with fallback chain
│   ├── memory.py       # State manager with conversation summarization
│   └── router.py       # Main pipeline orchestrator
├── config/
│   ├── models.yaml     # Model configuration per agent
│   └── prompts.yaml    # Prompt templates for each agent
├── storage/
│   └── redis_client.py # Redis-backed state persistence
├── main.py             # CLI entry point
└── requirements.txt    # Python dependencies
```

### Setup

```bash
cd ai-router
pip install -r requirements.txt
```

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENROUTER_API_KEY` | Yes | — | Your OpenRouter API key |
| `REDIS_HOST` | No | `localhost` | Redis server hostname |
| `REDIS_PORT` | No | `6379` | Redis server port |
| `USER_ID` | No | `default_user` | User identifier for state tracking |

### Usage

```bash
export OPENROUTER_API_KEY="your-key-here"
python main.py
```

### Features

- **Multi-agent pipeline**: 5 specialized agents (planner, coder, analyst, summarizer, validator)
- **Semantic compression**: LLM-based text compression that preserves meaning
- **Redis memory**: Persistent per-user state across sessions
- **OpenRouter integration**: Access to multiple LLM providers through a single API
- **Fallback chain**: Automatic failover across models if one is unavailable
- **Batch processing**: Queue and merge multiple requests for efficiency
