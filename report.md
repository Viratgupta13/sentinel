# Sentinel review: 🐛 Fix support for unions when using `Form`

PR: https://github.com/fastapi/fastapi/pull/13827  
Hunks: 3 total · 0 skipped (zero-cost) · 3 triaged · 1 deep-reviewed

## Findings

### 🔴 [HIGH] Potential NameError due to missing is_union_of_base_models definition or import
`fastapi/dependencies/utils.py` · hunk `fastapi/dependencies/utils.py#1` · confidence 85%

The added condition references is_union_of_base_models(first_field.type_) but the surrounding file does not show an import or definition for this function. If it is not defined elsewhere, importing fastapi will raise a NameError, preventing the application from starting and causing service outage.

**Suggestion:**

> Ensure is_union_of_base_models is defined in this module or imported from its proper location, and add appropriate unit tests covering both typing.Union and PEP 604 union syntax.

## Deep-reviewed hunks

| Hunk | Risk | Summary |
|---|---|---|
| `fastapi/dependencies/utils.py#1` | 7/10 | The change adds a check for unions of BaseModel types in _should_embed_body_fields, but the helper is_union_of_base_models may be undefined or improperly imported, risking a runtime NameError that would break FastAPI import and request handling. |

## Cost

| Model | Calls | Input | Output | Cache read | Cost (USD) |
|---|---|---|---|---|---|
| openai/gpt-oss-120b | 1 | 906 | 800 | 0 | $0.0000 |
| openai/gpt-oss-20b | 1 | 1,845 | 402 | 0 | $0.0000 |
| **Total** |  |  |  |  | **$0.0000** |
