# Error Extraction & Normalization Engine — RSR ErrorSentinel AI

## 1. Extraction Pipeline Overview

Extraction runs in two distinct stages:

### Stage 1: Deterministic Extraction (High Precision)
Configurable regular expressions match standardized enterprise error code formats:
- `ERR-\d+`, `ERROR-\d+`, `ERR_CODE-\d+`
- `HTTP 500`, `HTTP-404`, `HTTP 502`
- `SQLSTATE 42000`, `SQL-1234`
- `ORA-00942`, `ORA-01017`
- Named Exceptions (e.g. `TimeoutException`, `NullPointerException`, `DatabaseConnectionException`)

### Stage 2: AI Extraction (High Recall for Unstructured Context)
Extracts nested error codes from messy stack traces, email discussions, and log fragments. Returns validated structured JSON:
```json
{
  "errors": [
    {
      "error_code": "ERR-5021",
      "message": "Database connection timeout to primary cluster",
      "context": "Connection pool exhausted during transaction spike",
      "severity": "HIGH",
      "confidence": 0.95
    }
  ]
}
```

---

## 2. Normalization Rules

To prevent trivial differences from creating duplicate registry entries:
1. **Unicode Dash Folding**: Standardizes `–` (en-dash), `—` (em-dash), `−` (minus sign) to standard ASCII `-`.
2. **Case Normalization**: Uppercases prefixes (`err-5021` -> `ERR-5021`).
3. **Whitespace & Delimiters**: Cleans spaces, underscores, and extra hyphens (`Error_5021` -> `ERR-5021`).
4. **Dual Field Preservation**: Always preserves both `raw_code` and `normalized_code`.
