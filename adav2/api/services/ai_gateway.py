from sqlalchemy import text
from api.database import AsyncSessionLocal
from openai import AsyncOpenAI


async def get_openai_key():

    async with AsyncSessionLocal() as db:

        query = text("""
        SELECT key
        FROM api_keys
        WHERE service = 'openai'
        LIMIT 1
        """)

        result = await db.execute(query)
        row = result.fetchone()

        return row.key
    
async def call_openai(prompt: str):

    key = await get_openai_key()

    client = AsyncOpenAI(api_key=key)

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    return response.choices[0].message.content