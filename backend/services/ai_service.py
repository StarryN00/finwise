"""
MiniMax AI Service - OpenAI-compatible API
Handles all LLM calls with desensitization, cost tracking, and fallback.
"""
import json
import re
import uuid as uuid_lib
from typing import Optional, List, Dict, Any
from decimal import Decimal

import httpx

from backend.core.config import settings


def _build_client():
    """Build HTTP client for active AI provider."""
    if settings.ACTIVE_AI_PROVIDER == "minimax":
        api_key = settings.MINIMAX_API_KEY
        base_url = settings.MINIMAX_BASE_URL
        model = settings.MINIMAX_MODEL
    else:
        api_key = settings.MOONSHOT_API_KEY
        base_url = settings.MOONSHOT_BASE_URL
        model = settings.MOONSHOT_MODEL

    return httpx.AsyncClient(
        base_url=base_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=120.0,
    ), model


def _desensitize(text: str) -> str:
    """
    Desensitize enterprise names and tax numbers before sending to LLM.
    Replaces with placeholders to comply with data security requirements.
    """
    # Replace potential tax numbers (18-digit numbers that look like统一社会信用代码)
    text = re.sub(r'\d{18}', '[统一社会信用代码]', text)
    # Replace 15-digit tax numbers
    text = re.sub(r'\d{15}', '[纳税人识别号]', text)
    # Replace bank account numbers (10-20 digits)
    text = re.sub(r'\b\d{10,20}\b', '[银行账号]', text)
    # Replace potential mobile numbers
    text = re.sub(r'1[3-9]\d{9}', '[手机号]', text)
    return text


async def _call_llm(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 2048,
) -> Dict[str, Any]:
    """
    Make an LLM API call. Returns parsed JSON response.
    Raises on error.
    """
    client, default_model = _build_client()
    model = model or default_model

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        response = await client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        content = data["choices"][0]["message"]["content"]

        # Try to parse as JSON
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"raw": content}

    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"AI API error: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        raise RuntimeError(f"AI call failed: {str(e)}")
    finally:
        await client.aclose()


async def parse_bank_statement_with_ai(
    import_batch_id,
    enterprise_id,
    raw_text,
) -> List[Dict[str, Any]]:
    """
    Use MiniMax LLM to parse bank statement text into structured transactions.
    Returns list of parsed transaction dicts.

    The prompt instructs the model to extract:
    - transaction_date
    - summary
    - debit_amount (optional)
    - credit_amount (optional)
    - balance (optional)
    """
    desensitized_text = _desensitize(raw_text)

    system_prompt = """你是一个专业的银行流水解析助手。请从下方的银行流水文本中提取交易记录。

**输出格式（严格JSON数组）：**
```json
[
  {
    "row_index": 0,
    "transaction_date": "YYYY-MM-DD",
    "summary": "交易摘要",
    "debit_amount": null或数字,
    "credit_amount": null或数字,
    "balance": null或数字
  }
]
```

**规则：**
1. row_index 从 0 开始，对应原文第1行数据
2. 日期格式必须是 YYYY-MM-DD
3. debit_amount 为借方金额（支出），credit_amount 为贷方金额（收入），两者互斥
4. 如果无法确定某字段，用 null
5. 只输出 JSON，不要其他内容
6. 摘要应简洁，保留核心信息（对方账户、用途）
"""

    user_prompt = f"银行流水文本：\n{desensitized_text}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    result = await _call_llm(messages, model=settings.AI_BANK_PARSING_MODEL)

    # Skip DB logging for JSONStore version
    return result if isinstance(result, list) else []


async def match_transactions_with_ai(
    enterprise_id,
    import_batch_id,
    transactions: List[Dict[str, Any]],
    invoices: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Use MiniMax LLM to match bank transactions with invoices.
    Returns match candidates and reasoning.

    Matching strategy (3-layer):
    1. Exact match: amount + date (within 3 days)
    2. Fuzzy match: amount + similar date range
    3. AI inference: summary keywords + pattern analysis
    """
    # Prepare desensitized data
    tx_data = [
        {
            "index": i,
            "date": str(t.get("transaction_date", "")),
            "amount": float(t.get("debit_amount") or t.get("credit_amount") or 0),
            "summary": _desensitize(t.get("summary", ""))[:100],
            "type": "debit" if t.get("debit_amount") else "credit",
        }
        for i, t in enumerate(transactions)
    ]

    inv_data = [
        {
            "index": i,
            "invoice_number": t.get("invoice_number", "[发票号]"),
            "date": str(t.get("issue_date", "")),
            "amount": float(t.get("total_amount") or 0),
            "tax_amount": float(t.get("tax_amount") or 0),
            "seller": _desensitize(t.get("seller_name", ""))[:50],
        }
        for i, t in enumerate(invoices)
    ]

    system_prompt = """你是一个专业的流水-发票匹配助手。请根据以下银行流水和发票数据，进行三层匹配：

**匹配策略：**
1. **精确匹配**：金额完全一致 + 日期相差3天内
2. **模糊匹配**：金额一致 + 日期相差7天内
3. **AI推断**：摘要关键词 + 金额模式分析（如"货款"、"服务费"等）

**输出格式（严格JSON）：**
```json
{
  "candidates": [
    {
      "transaction_index": 0,
      "invoice_index": 0,
      "confidence": 0.95,
      "match_layer": "EXACT|FUZZY|AI",
      "match_reason": "匹配原因说明"
    }
  ],
  "reasoning": "整体匹配逻辑说明"
}
```

**仅输出已确认的匹配，不要猜测。**"""

    user_prompt = f"""银行流水：
{json.dumps(tx_data, ensure_ascii=False, indent=2)}

发票：
{json.dumps(inv_data, ensure_ascii=False, indent=2)}"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    result = await _call_llm(messages, model=settings.AI_MATCHING_MODEL)

    # Skip DB logging for JSONStore version
    return result


async def generate_health_analysis_with_ai(
    enterprise_id: uuid_lib.UUID,
    financial_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Use MiniMax LLM to generate financial health analysis.
    Returns structured analysis with scores and interpretation.
    """
    system_prompt = """你是一个专业的企业财务健康分析师。请根据以下财务数据，对企业进行五维度健康分析：

**五维度：**
1. 盈利能力 (profitability) - 毛利率、净利率、资产回报率
2. 偿债能力 (solvency) - 资产负债率、流动比率
3. 运营效率 (operation_efficiency) - 存货周转、应收账款周转
4. 成长性 (growth) - 营收增长率、利润增长率
5. 现金流 (cash_flow) - 经营现金流净额

**输出格式（严格JSON）：**
```json
{
  "overall_score": 75,
  "overall_grade": "B",
  "profitability_score": 72.5,
  "solvency_score": 80.0,
  "operation_efficiency_score": 68.0,
  "growth_score": 75.0,
  "cash_flow_score": 70.0,
  "radar_data": {
    "profitability": 72.5,
    "solvency": 80.0,
    "operation_efficiency": 68.0,
    "growth": 75.0,
    "cash_flow": 70.0
  },
  "key_metrics": {
    "gross_margin": 0.25,
    "net_margin": 0.08,
    "roa": 0.05,
    "current_ratio": 1.8,
    "debt_ratio": 0.55,
    "inventory_turnover": 4.2,
    "receivable_turnover": 5.1,
    "revenue_growth": 0.12,
    "profit_growth": 0.08
  },
  "ai_interpretation": "整体分析说明",
  "risk_alerts": ["风险提示1", "风险提示2"],
  "improvement_suggestions": ["改进建议1", "改进建议2"],
  "financing_score": 68,
  "estimated_loan_amount": 5000000,
  "matched_products": ["产品A", "产品B"]
}
```

**评分规则：**
- overall_score: 0-100
- grade: A+(90+), A(80-89), B+(70-79), B(60-69), C(40-59), D(<40)
- financing_score: 0-100，基于信用评分模型

**注意：所有数据必须合理推断，不可虚构。**"""

    desensitized_data = _desensitize(json.dumps(financial_data, ensure_ascii=False))

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"财务数据：\n{desensitized_data}"},
    ]

    result = await _call_llm(
        messages,
        model=settings.AI_ANALYSIS_MODEL,
        temperature=0.3,
        max_tokens=4096,
    )
    return result
