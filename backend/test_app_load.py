"""
Test script to verify FastAPI app loads correctly.
"""
import os
import sys

os.environ["TESTING"] = "true"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_finwise.db"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient


def test_app_load():
    """Test that the FastAPI app can be imported and instantiated."""
    from main import app

    client = TestClient(app)

    # Test health endpoint
    response = client.get("/api/health")
    assert response.status_code == 200, f"Health check failed: {response.status_code}"
    data = response.json()
    print(f"Health check response: {data}")
    assert data["status"] == "ok"

    print("FastAPI app loaded successfully!")
    return True


def test_db_connect():
    """Test database connectivity."""
    from core.database import async_session_maker, init_db
    import asyncio

    async def _test():
        await init_db()
        async with async_session_maker() as session:
            from sqlalchemy import text
            result = await session.execute(text("SELECT 1"))
            print(f"DB test result: {result.scalar()}")
            return True

    asyncio.run(_test())
    print("Database connection OK")
    return True


if __name__ == "__main__":
    print("=== Testing FinWise FastAPI App ===")
    print(f"TESTING={os.environ.get('TESTING')}")
    print(f"DATABASE_URL={os.environ.get('DATABASE_URL')}")

    try:
        test_db_connect()
        test_app_load()
        print("\n=== All tests passed ===")
    except Exception as e:
        print(f"\n=== Test failed: {e} ===")
        import traceback
        traceback.print_exc()
        sys.exit(1)