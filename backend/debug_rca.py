import asyncio
import os
import sys

# Add the backend directory to sys.path so 'app' can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.agents.rca import generate_rca
from app.api.alerts import GenericAlert

async def main():
    alert = GenericAlert(source="test", title="Test Alert")
    investigation = {"symptoms": "Test"}
    rca = await generate_rca(alert, investigation)
    print("RCA RESULT:")
    print(rca)

if __name__ == "__main__":
    asyncio.run(main())
