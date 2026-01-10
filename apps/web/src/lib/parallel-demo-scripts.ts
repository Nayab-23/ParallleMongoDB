export const PARALLEL_DEMO_SCRIPTS = [
  {
    q: "Nayab didn't push yet-what changed in app.py?",
    a: "Refactored routes into a router, added scoped auth checks, tightened validation, and improved error handling/logging.",
  },
  {
    q: "Explain Nayab's frontend.py change-what did he do?",
    a: "Split UI into smaller components, moved API calls into a client helper, standardized state handling, and improved render performance.",
  },
  {
    q: "We need it now-can you push his pending commits?",
    a: "Rebased his branch, ran tests, committed the fixes, pushed the branch, and opened a PR ready to merge.",
  },
] as const;
