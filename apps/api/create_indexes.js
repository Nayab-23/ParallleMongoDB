// MongoDB Atlas Index Creation Script
// Run this in mongosh or MongoDB Compass

// Switch to database
use parallel_demo;

print("Creating indexes for Web ↔ Extension integration...\n");

// ============================================
// CHATS
// ============================================
print("Creating chats indexes...");
db.chats.createIndex({chat_id: 1}, {unique: true, name: "chat_id_unique"});
db.chats.createIndex(
  {workspace_id: 1, updated_at: -1},
  {name: "workspace_updated"}
);
print("✓ chats indexes created\n");

// ============================================
// MESSAGES
// ============================================
print("Creating messages indexes...");
db.messages.createIndex(
  {message_id: 1},
  {unique: true, name: "message_id_unique"}
);
db.messages.createIndex(
  {chat_id: 1, created_at: -1},
  {name: "chat_created"}
);
print("✓ messages indexes created\n");

// ============================================
// TASKS
// ============================================
print("Creating tasks indexes...");
db.tasks.createIndex({task_id: 1}, {unique: true, name: "task_id_unique"});
db.tasks.createIndex(
  {workspace_id: 1, status: 1, created_at: -1},
  {name: "workspace_status_created"}
);
db.tasks.createIndex({chat_id: 1}, {name: "chat_id"});
print("✓ tasks indexes created\n");

// ============================================
// EVENTS (for SSE)
// ============================================
print("Creating events indexes...");
db.events.createIndex({event_id: 1}, {unique: true, name: "event_id_unique"});
db.events.createIndex(
  {workspace_id: 1, created_at: -1},
  {name: "workspace_created"}
);
print("✓ events indexes created\n");

// ============================================
// EDITS
// ============================================
print("Creating edits indexes...");
db.edits.createIndex({edit_id: 1}, {unique: true, name: "edit_id_unique"});
db.edits.createIndex(
  {workspace_id: 1, created_at: -1},
  {name: "workspace_created"}
);
print("✓ edits indexes created\n");

// ============================================
// VERIFY
// ============================================
print("\nVerifying indexes...\n");

print("chats:");
printjson(db.chats.getIndexes());

print("\nmessages:");
printjson(db.messages.getIndexes());

print("\ntasks:");
printjson(db.tasks.getIndexes());

print("\nevents:");
printjson(db.events.getIndexes());

print("\nedits:");
printjson(db.edits.getIndexes());

print("\n✅ All indexes created successfully!");
print("\nNext steps:");
print("1. Start backend: cd apps/api && python -m uvicorn hack_main:app --reload --port 8000");
print("2. Run smoke tests: See apps/api/SMOKE_TEST.md");
