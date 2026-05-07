"""
Test script for MiniMax API integration.
Run: python -m backend.test_minimax
"""
import asyncio
import json
import re

import httpx

# Configuration
MINIMAX_API_KEY = "your_api_key_here"
MINIMAX_BASE_URL = "https://api.minimax.io/v1"
MODEL = "MiniMax-Text-01"


def _desensitize(text: str) -> str:
    text = re.sub(r'\d{18}', '[统一社会信用代码]', text)
    text = re.sub(r'\d{15}', '[纳税人识别号]', text)
    text = re.sub(r'\b\d{10,20}\b', '[银行账号]', text)
    text = re.sub(r'1[3-9]\d{9}', '[手机号]', text)
    return text


async def test_chat():
    """Test basic chat completion."""
    print("=" * 60)
    print("Testing MiniMax Chat Completion")
    print("=" * 60)

    client = httpx.AsyncClient(
        base_url=MINIMAX_BASE_URL,
        headers={
            "Authorization": f"Bearer {MINIMAX_API_KEY}",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )

    messages = [
        {"role": "user", "content": "Hello, what is 2+2?"}
    ]

    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 100,
    }

    try:
        response = await client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        content = data["choices"][0]["message"]["content"]
        print(f"Response: {content}")
        print(f"Model: {data.get('model')}")
        print(f"Usage: {data.get('usage')}")
        return True

    except httpx.HTTPStatusError as e:
        print(f"HTTP Error: {e.response.status_code}")
        print(f"Response: {e.response.text}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False
    finally:
        await client.aclose()


async def test_bank_statement_parsing():
    """Test bank statement parsing with MiniMax."""
    print("\n" + "=" * 60)
    print("Testing Bank Statement Parsing")
    print("=" * 60)

    sample_bank_statement = """
日期,摘要,借方金额,贷方金额,余额
2026-03-01,收到货款,0.00,50000.00,50000.00
2026-03-02,支付供应商A,20000.00,0.00,30000.00
2026-03-03,收到货款,0.00,30000.00,60000.00
2026-03-04,支付水电费,1500.00,0.00,58500.00
2026-03-05,收到货款,0.00,80000.00,138500.00
2026-03-06,支付运费,2000.00,0.00,136500.00
    """.strip()

    desensitized = _desensitize(sample_bank_statement)

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
1. row_index 从 0 开始
2. 日期格式必须是 YYYY-MM-DD
3. debit_amount 为借方金额（支出），credit_amount 为贷方金额（收入）
4. 只输出 JSON，不要其他内容
"""

    client = httpx.AsyncClient(
        base_url=MINIMAX_BASE_URL,
        headers={
            "Authorization": f"Bearer {MINIMAX_API_KEY}",
            "Content-Type": "application/json",
        },
        timeout=60.0,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"银行流水文本：\n{desensitized}"},
    ]

    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 2048,
    }

    try:
        response = await client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        content = data["choices"][0]["message"]["content"]
        print(f"Raw response:\n{content}")

        # Try to parse as JSON
        result = json.loads(content)
        print(f"\nParsed {len(result)} transactions:")
        for tx in result:
            print(f"  [{tx['row_index']}] {tx['transaction_date']} | {tx['summary']} | 借:{tx.get('debit_amount')} 贷:{tx.get('credit_amount')} 余额:{tx.get('balance')}")

        return result

    except httpx.HTTPStatusError as e:
        print(f"HTTP Error: {e.response.status_code}")
        print(f"Response: {e.response.text}")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None
    finally:
        await client.aclose()


async def test_matching():
    """Test transaction-invoice matching."""
    print("\n" + "=" * 60)
    print("Testing Transaction-Invoice Matching")
    print("=" * 60)

    transactions = [
        {"index": 0, "date": "2026-03-01", "amount": 50000.0, "summary": "收到货款", "type": "credit"},
        {"index": 1, "date": "2026-03-02", "amount": 20000.0, "summary": "支付供应商A", "type": "debit"},
        {"index": 2, "date": "2026-03-03", "amount": 30000.0, "summary": "收到货款", "type": "credit"},
    ]

    invoices = [
        {"index": 0, "invoice_number": "FP202603001", "date": "2026-03-01", "amount": 50000.0, "tax_amount": 5000.0, "seller": "[公司名]"},
        {"index": 1, "invoice_number": "FP202603002", "date": "2026-03-03", "amount": 30000.0, "tax_amount": 3000.0, "seller": "[公司名]"},
    ]

    system_prompt = """你是一个专业的流水-发票匹配助手。请根据以下银行流水和发票数据，进行三层匹配：

**匹配策略：**
1. **精确匹配**：金额完全一致 + 日期相差3天内
2. **模糊匹配**：金额一致 + 日期相差7天内
3. **AI推断**：摘要关键词 + 金额模式分析

**输出格式（严格JSON）：**
```json
{
  "candidates": [
    {
      "transaction_index": 0,
      "invoice_index": 0,
      "confidence": 0.95,
      "match_layer": "EXACT",
      "match_reason": "匹配原因"
    }
  ]
}
```
"""

    user_prompt = f"""银行流水：
{json.dumps(transactions, ensure_ascii=False, indent=2)}

发票：
{json.dumps(invoices, ensure_ascii=False, indent=2)}"""

    client = httpx.AsyncClient(
        base_url=MINIMAX_BASE_URL,
        headers={
            "Authorization": f"Bearer {MINIMAX_API_KEY}",
            "Content-Type": "application/json",
        },
        timeout=60.0,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 2048,
    }

    try:
        response = await client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        content = data["choices"][0]["message"]["content"]
        print(f"Raw response:\n{content}")

        result = json.loads(content)
        print(f"\nMatched {len(result.get('candidates', []))} pairs:")
        for cand in result.get("candidates", []):
            print(f"  流水[{cand['transaction_index']}] <-> 发票[{cand['invoice_index']}] "
                  f"置信度:{cand['confidence']} 层:{cand['match_layer']} 原因:{cand['match_reason']}")

        return result

    except httpx.HTTPStatusError as e:
        print(f"HTTP Error: {e.response.status_code}")
        print(f"Response: {e.response.text}")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None
    finally:
        await client.aclose()


async def main():
    """Run all tests."""
    print("\n🚀 FinWise MiniMax Integration Test\n")

    # Test 1: Basic chat
    await test_chat()

    # Test 2: Bank statement parsing
    await test_bank_statement_parsing()

    # Test 3: Transaction-invoice matching
    await test_matching()

    print("\n✅ All tests completed!")


if __name__ == "__main__":
    asyncio.run(main())
