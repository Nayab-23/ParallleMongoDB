import openai
import json
from datetime import datetime

def summarize_brief_data(emails: list, events: list, user_name: str) -> dict:
    """
    Takes raw Gmail/Calendar data and returns AI-processed summaries
    formatted for the frontend components.
    """
    
    # Build context for the AI
    email_context = "\n".join([
        f"- From: {e['from']}, Subject: {e['subject']}, Snippet: {e['snippet']}"
        for e in emails[:15]  # Limit to 15 to avoid token overflow
    ])
    
    calendar_context = "\n".join([
        f"- {e['summary']} at {e['start_time']} ({e.get('location', 'No location')})"
        for e in events[:10]
    ])
    
    prompt = f"""You are generating a Daily Brief for {user_name}.

EMAILS ({len(emails)} unread):
{email_context or "No unread emails"}

CALENDAR (next 2 days):
{calendar_context or "No upcoming meetings"}

Generate a JSON response with these exact keys:

{{
  "priorities": [
    {{"title": "Top priority action", "detail": "Why it matters"}},
    // 3-5 priorities max
  ],
  "unread_emails": [
    {{"title": "Action: Reply to John's design feedback", "detail": "Urgent - needs response by EOD", "link": "https://mail.google.com/..."}},
    // Only emails needing ACTION (3-5 max)
  ],
  "upcoming_meetings": [
    {{"title": "Standup at 10am", "detail": "Prepare: yesterday's progress update"}},
    // All meetings today + tomorrow, with prep suggestions
  ],
  "actions": [
    {{"title": "Review Q4 roadmap before 2pm call", "detail": "High priority"}},
    // Suggested next actions based on emails/calendar (3-5 max)
  ]
}}

RULES:
1. For emails: Only include ones needing ACTION. Skip newsletters/FYI.
2. For meetings: Add "Prepare: X" detail for important meetings.
3. For priorities: Extract from both emails AND meetings. Be specific.
4. For actions: Actionable next steps, not vague suggestions.
5. Keep titles SHORT (under 60 chars). Details under 100 chars.
6. Return ONLY valid JSON, no markdown formatting.
"""

    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",  # Cheaper, faster for summarization
            messages=[
                {"role": "system", "content": "You are a helpful assistant that generates structured daily briefs. Always return valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,  # Lower = more consistent
            max_tokens=1000
        )
        
        content = response.choices[0].message.content.strip()
        
        # Remove markdown code fences if present
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()
        
        result = json.loads(content)
        
        # Validate structure
        expected_keys = ["priorities", "unread_emails", "upcoming_meetings", "actions"]
        for key in expected_keys:
            if key not in result:
                result[key] = []
        
        return result
        
    except Exception as e:
        print(f"Error in AI summarization: {e}")
        # Fallback to simple formatting
        return {
            "priorities": [],
            "unread_emails": [
                {"title": e["subject"], "detail": f"From: {e['from']}", "link": ""}
                for e in emails[:5]
            ],
            "upcoming_meetings": [
                {"title": e["summary"], "detail": f"at {e.get('start_time', 'TBD')}"}
                for e in events[:5]
            ],
            "actions": []
        }
    
def summarize_team_activity(user, db) -> list:
    """
    Get recent team activity from rooms and summarize it.
    """
    from app.models import Message, Room, RoomMember
    from datetime import timedelta
    
    # Get user's rooms
    room_ids = db.query(RoomMember.room_id).filter(
        RoomMember.user_id == user.id
    ).all()
    room_ids = [r[0] for r in room_ids]
    
    if not room_ids:
        return []
    
    # Get messages from last 24 hours
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    messages = db.query(Message).join(Room).filter(
        Message.room_id.in_(room_ids),
        Message.created_at >= since,
        Message.sender_id != user.id  # Exclude own messages
    ).order_by(Message.created_at.desc()).limit(50).all()
    
    if not messages:
        return []
    
    # Group by sender
    activity_by_person = {}
    for msg in messages:
        sender = msg.sender.name or msg.sender.email.split('@')[0]
        if sender not in activity_by_person:
            activity_by_person[sender] = []
        activity_by_person[sender].append(msg.content[:200])  # Truncate
    
    # Build context for AI
    context = "\n\n".join([
        f"{sender}:\n" + "\n".join([f"- {msg}" for msg in msgs[:3]])
        for sender, msgs in list(activity_by_person.items())[:10]
    ])
    
    prompt = f"""Summarize recent team activity into 3-5 key updates.

RECENT MESSAGES:
{context}

Return JSON array:
[
  {{"title": "Yug is blocked on API integration", "detail": "Waiting for OAuth credentials from IT"}},
  {{"title": "Sean shipped new auth flow", "detail": "JWT tokens now refresh automatically"}},
  ...
]

Focus on:
- Blockers/issues team members mentioned
- Completed work/shipped features
- Questions needing answers
- Important decisions made

Keep titles SHORT and ACTIONABLE. Return ONLY valid JSON array.
"""

    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are summarizing team activity. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=500
        )
        
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()
        
        return json.loads(content)
        
    except Exception as e:
        print(f"Error summarizing team activity: {e}")
        # Fallback: just show raw recent messages
        return [
            {"title": f"{msg.sender.name}: {msg.content[:50]}...", "detail": ""}
            for msg in messages[:5]
        ]