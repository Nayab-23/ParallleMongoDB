/**
 * Detect if a message needs RAG (historical context retrieval)
 * Returns true if message likely needs data beyond recent context window
 */
export function shouldUseRAG(message) {
  if (!message || typeof message !== "string" || message.length < 10) return false;

  const lowerMsg = message.toLowerCase();

  // Temporal triggers - looking back in time
  const temporalPatterns = [
    /last (week|month|year)/,
    /\d+ (weeks?|months?|days?) ago/,
    /earlier|previously|before|past/,
    /(what|when) did (we|i)/,
  ];

  // Search triggers - explicit search intent
  const searchPatterns = [
    /find (all|every|any)/,
    /search (for|my|our)/,
    /look (for|up|back)/,
    /show me (all|every)/,
    /recall|remember/,
  ];

  // Summary triggers - need to aggregate
  const summaryPatterns = [
    /summarize (all|everything)/,
    /give me (an? )?(overview|summary)/,
    /all (discussions?|messages?|conversations?)/,
    /everything (about|related to)/,
  ];

  const hasTemporalTrigger = temporalPatterns.some((p) => p.test(lowerMsg));
  const hasSearchTrigger = searchPatterns.some((p) => p.test(lowerMsg));
  const hasSummaryTrigger = summaryPatterns.some((p) => p.test(lowerMsg));

  const isComplexQuery = message.length > 250;
  const hasAggregationIntent = /\b(all|every|entire)\b/.test(lowerMsg);

  return (
    hasTemporalTrigger ||
    hasSearchTrigger ||
    hasSummaryTrigger ||
    (isComplexQuery && hasAggregationIntent)
  );
}

/**
 * Get explanation for why RAG was triggered (for debugging/UI)
 */
export function getRAGTriggerReason(message) {
  if (!message || typeof message !== "string") return "Searching history";
  const lowerMsg = message.toLowerCase();

  if (/last (week|month|year)|\d+ (weeks?|months?|days?) ago/.test(lowerMsg)) {
    return "Searching history (temporal query)";
  }
  if (/find|search|look for|show me/.test(lowerMsg)) {
    return "Searching history (search query)";
  }
  if (/summarize|overview|all discussions/.test(lowerMsg)) {
    return "Searching history (summary request)";
  }
  if (message.length > 250) {
    return "Searching history (complex query)";
  }
  return "Searching history";
}
