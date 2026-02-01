# Troubleshooting: "setIsFileSelectorOpen is not a function"

## Problem
Getting a runtime error `setIsFileSelectorOpen is not a function` on dev server but not locally.

## Root Cause
This is typically caused by **stale localStorage data** from an older version of the application. The Zustand store uses localStorage persistence, and if the state shape changes between versions, it can cause function references to be lost or corrupted.

## Solutions

### Option 1: Clear Cache via Browser Console (Quickest)
1. Open your dev server in the browser
2. Open Developer Tools (F12)
3. Go to Console tab
4. Type: `localStorage.clear()` and press Enter
5. Refresh the page

### Option 2: Use the Clear Cache Page
1. Navigate to: `http://your-dev-server/clear-cache`
2. Click "Clear Cache & Reload"
3. The page will automatically redirect to home

### Option 3: Manual Browser Cache Clear
1. Open Developer Tools (F12)
2. Go to Application tab (Chrome) or Storage tab (Firefox)
3. Find "Local Storage" in the sidebar
4. Right-click on your domain and select "Clear"
5. Refresh the page

### Option 4: Increment Store Version (For Future Prevention)
The store version has been set in `/lib/store.ts`. To force a migration in the future:
1. Open `/lib/store.ts`
2. Find the `version` field in the persist config
3. Increment it: `version: 2` (currently set to 1)
4. Update the migration function if needed

## Prevention
The following changes have been applied to prevent this issue:

1. **Added version control** to the Zustand store persistence
2. **Added error handling** in ViewerHeader component with fallback to reload
3. **Created a clear-cache utility page** at `/clear-cache`

## Why This Happens

### Local vs Dev Server Differences:
- **Local**: Fresh cache or recent build → store functions work correctly
- **Dev Server**: Stale cache from previous version → corrupted store state

### Zustand Persistence:
- The store persists certain state to localStorage for user preferences
- When code changes but localStorage isn't cleared, mismatches occur
- Function references can't be serialized, so they're lost if state is corrupted

## Quick Reference
```bash
# After deploying new changes, users may need to:
# 1. Clear localStorage
# 2. Or visit /clear-cache
# 3. Or increment version in store.ts
```

## Technical Details
- **File**: `lib/store.ts` - Main Zustand store with persistence
- **Component**: `components/viewer/ViewerHeader.tsx` - Where error occurs
- **Storage Key**: `viewer-preferences` - localStorage key used by the store
