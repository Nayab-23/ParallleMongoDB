import asyncio
import sys
from pathlib import Path

from openai import AsyncOpenAI
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import SessionLocal
from models import Message

client = AsyncOpenAI()

async def generate_embedding(text: str):
    """Generate embedding for a single text"""
    response = await client.embeddings.create(
        model="text-embedding-3-small",  # Cheaper than ada-002, same quality
        input=text
    )
    return response.data[0].embedding

async def backfill_embeddings():
    """Generate embeddings for all existing messages"""
    db = SessionLocal()
    
    # Get all messages without embeddings
    messages = db.execute(
        select(Message).where(Message.embedding.is_(None))
    ).scalars().all()
    
    print(f"Found {len(messages)} messages to embed")
    
    for i, message in enumerate(messages):
        # Combine content with metadata for richer embeddings
        text_to_embed = f"{message.content}"
        
        # Generate embedding
        embedding = await generate_embedding(text_to_embed)
        
        # Update message
        message.embedding = embedding
        db.commit()
        
        if i % 10 == 0:
            print(f"Processed {i}/{len(messages)}")
    
    print("Done!")
    db.close()

if __name__ == "__main__":
    asyncio.run(backfill_embeddings())
