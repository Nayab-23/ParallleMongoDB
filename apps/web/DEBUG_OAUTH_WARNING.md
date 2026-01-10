# OAuth Warning Debug Guide

## Step 1: Test the API Response

Open the Daily Brief page and paste this into your browser console:

```javascript
// Test /api/canon endpoint
fetch('https://api.parallelos.ai/api/canon', {
  credentials: 'include',
  headers: {
    'Content-Type': 'application/json'
  }
})
.then(r => r.json())
.then(data => {
  console.log('=== CANON API DEBUG ===');
  console.log('Full response:', data);
  console.log('\n--- OAuth Status ---');
  console.log('needs_reconnect (top-level):', data.needs_reconnect);
  console.log('data_stale:', data.data_stale);
  console.log('last_sync:', data.last_sync);

  console.log('\n--- Integrations ---');
  console.log('integrations object:', data.integrations);

  if (data.integrations) {
    console.log('\nGmail:', {
      connected: data.integrations.gmail?.connected,
      healthy: data.integrations.gmail?.healthy,
      needs_reconnect: data.integrations.gmail?.needs_reconnect
    });

    console.log('\nCalendar:', {
      connected: data.integrations.calendar?.connected,
      healthy: data.integrations.calendar?.healthy,
      needs_reconnect: data.integrations.calendar?.needs_reconnect
    });
  }

  console.log('\n--- Validation Checks ---');

  // Validation
  const checks = {
    'Top-level needs_reconnect is true': data.needs_reconnect === true,
    'Gmail needs_reconnect is true': data.integrations?.gmail?.needs_reconnect === true,
    'Calendar needs_reconnect is true': data.integrations?.calendar?.needs_reconnect === true,
    'At least one integration needs reconnect':
      data.needs_reconnect === true ||
      data.integrations?.gmail?.needs_reconnect === true ||
      data.integrations?.calendar?.needs_reconnect === true
  };

  Object.entries(checks).forEach(([check, passed]) => {
    console.log(`${passed ? '✅' : '❌'} ${check}`);
  });

  if (!checks['At least one integration needs reconnect']) {
    console.error('\n❌ WARNING WILL NOT DISPLAY - No reconnection needed');
  } else {
    console.log('\n✅ WARNING SHOULD DISPLAY');
  }
})
.catch(err => {
  console.error('API Error:', err);
});
```

## Step 2: Check React Component State

After the page loads, check what the React component received:

```javascript
// This will be logged automatically by the debug code we added
// Look for these console messages:
// [Canon API] Raw response: {...}
// [Canon API] Constructed canonPersonal: {...}
// [DailyBrief] filteredPersonal debug: {...}
// [DailyBrief Render] OAuth Warning Debug: {...}
```

## Step 3: Manual Warning Display Test

If the warning still doesn't show, force it to display:

```javascript
// Add temporary CSS to make warning visible even if React didn't render it
const style = document.createElement('style');
style.innerHTML = `
  .integration-warning {
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
  }
`;
document.head.appendChild(style);

// Check if warning element exists in DOM
const warning = document.querySelector('.integration-warning');
if (warning) {
  console.log('✅ Warning element found in DOM:', warning);
  console.log('Element computed style:', window.getComputedStyle(warning));
} else {
  console.error('❌ Warning element NOT in DOM - React condition failed');
}
```

## Step 4: Check for CSS Issues

```javascript
// Check if CSS is hiding the warning
const warning = document.querySelector('.integration-warning');
if (warning) {
  const styles = window.getComputedStyle(warning);
  console.log('Warning element styles:', {
    display: styles.display,
    visibility: styles.visibility,
    opacity: styles.opacity,
    position: styles.position,
    zIndex: styles.zIndex,
  });
}
```

## Expected Debug Output

When everything is working correctly, you should see:

```
[Canon API] Raw response: {
  needs_reconnect: true,
  data_stale: true,
  integrations: {
    gmail: { connected: true, healthy: false, needs_reconnect: true },
    calendar: { connected: true, healthy: false, needs_reconnect: true }
  },
  last_sync: "2025-12-22T10:30:00Z"
}

[Canon API] Constructed canonPersonal: {
  timeline: {...},
  priorities: [...],
  integrations: {
    gmail: { connected: true, healthy: false, needs_reconnect: true },
    calendar: { connected: true, healthy: false, needs_reconnect: true }
  },
  data_stale: true,
  needs_reconnect: true,
  last_sync: "2025-12-22T10:30:00Z"
}

[DailyBrief] filteredPersonal debug: {
  needs_reconnect: true,
  data_stale: true,
  integrations: {...},
  last_sync: "2025-12-22T10:30:00Z",
  personalData_needs_reconnect: true,
  personalData_integrations: {...}
}

[DailyBrief Render] OAuth Warning Debug: {
  filteredPersonal_exists: true,
  needs_reconnect_value: true,
  needs_reconnect_type: "boolean",
  integrations: {...},
  gmail_needs_reconnect: true,
  calendar_needs_reconnect: true,
  data_stale: true,
  last_sync: "2025-12-22T10:30:00Z",
  will_show_warning: true
}
```

## Common Issues and Fixes

### Issue 1: `needs_reconnect` is `false` but integrations show `true`

**Fix:** The updated code now checks both top-level AND individual integration flags:
```javascript
{(filteredPersonal?.needs_reconnect ||
  filteredPersonal?.integrations?.gmail?.needs_reconnect ||
  filteredPersonal?.integrations?.calendar?.needs_reconnect) && (
  // Warning component
)}
```

### Issue 2: Data is present but warning doesn't render

**Check:**
1. Look for React errors in console
2. Check if component is rendering at all
3. Verify the warning is inside the correct conditional block (personal tab)

**Fix:** Make sure you're on the "Personal" tab, not "Org" or "Outbound"

### Issue 3: Warning renders but is hidden

**Check:** CSS specificity or z-index issues

**Fix:**
```javascript
// In browser console
document.querySelector('.integration-warning').style.cssText =
  'display: flex !important; visibility: visible !important; opacity: 1 !important;';
```

### Issue 4: API returns correct data but React state doesn't update

**Check:** Debug logs show API response but filteredPersonal is missing the fields

**Possible cause:**
- State update timing issue
- Component unmounting before state updates
- External props overriding state

**Fix:** Check if `externalPersonalData` prop is being passed and overriding the canon data

## Testing Checklist

After applying fixes:

- [ ] Open browser console
- [ ] Navigate to Daily Brief page (Personal tab)
- [ ] See `[Canon API] Raw response:` log
- [ ] See `[DailyBrief Render] OAuth Warning Debug:` log
- [ ] Verify `needs_reconnect: true` in logs
- [ ] See orange warning banner in UI
- [ ] Click "Reconnect in Settings" link
- [ ] Navigate to Settings page
- [ ] See "⚠️ Expired" badge on Gmail/Calendar
- [ ] See orange "Reconnect" button
