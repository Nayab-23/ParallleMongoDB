import asyncio
import os
import sys
from pathlib import Path

from openai import AsyncOpenAI
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import SessionLocal
from models import Message
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file

# Set OpenAI API key from environment # a
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def generate_embedding(text: str):
    """Generate embedding for a single text"""
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=text[:8000]  # Truncate to avoid token limit errors
    )
    return response.data[0].embedding

async def backfill_embeddings():
    """Generate embeddings for all existing messages"""
    db = SessionLocal()
    
    try:
        # Get all messages without embeddings
        messages = db.execute(
            select(Message).where(Message.embedding.is_(None))
        ).scalars().all()
        
        print(f"Found {len(messages)} messages to embed")
        
        for i, message in enumerate(messages):
            try:
                # Generate embedding
                embedding = await generate_embedding(message.content)
                
                # Update message
                message.embedding = embedding
                
                # Commit every 10 messages to avoid losing progress
                if i % 10 == 0:
                    db.commit()
                    print(f"Processed {i}/{len(messages)}")
                    
            except Exception as e:
                print(f"Error embedding message {message.id}: {e}")
                continue
        
        # Final commit for any remaining messages
        db.commit()
        print("Done!")
        
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(backfill_embeddings())
