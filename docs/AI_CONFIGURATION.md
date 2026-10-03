# AI & LLM Configuration Guide — RSR ErrorSentinel AI

ErrorSentinel uses a hybrid intelligence engine combining deterministic regular expressions with AI models.

## 1. Supported AI Providers

- `mock`: Built-in offline mock provider for development and automated testing. Requires no keys.
- `openai`: OpenAI GPT-4o, GPT-4o-mini, etc.
- `gemini`: Google Gemini 1.5 Flash / Pro.
- `ollama`: Local offline LLMs (Llama 3, Mistral, etc.).
- `none` / `disabled`: Runs strictly with deterministic Stage 1 regex extraction.

---

## 2. Setting Up OpenAI

In `.env`:
```ini
LLM_PROVIDER=openai
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
MAX_LLM_CONCURRENCY=3
```

---

## 3. Setting Up Google Gemini

In `.env`:
```ini
LLM_PROVIDER=gemini
LLM_API_KEY=AIzaSy...
LLM_MODEL=gemini-1.5-flash
```

---

## 4. Architectural Boundaries

- **The LLM is NEVER the authority on whether an error is NEW or EXISTING.**
- Python + Master Registry Database deterministically performs exact lookups.
- AI is used solely for unstructured extraction, root-cause assessment, grouping, and executive summary writing.
