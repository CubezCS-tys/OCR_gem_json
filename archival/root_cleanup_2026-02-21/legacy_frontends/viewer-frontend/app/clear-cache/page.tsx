"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { useRouter } from "next/navigation";

export default function ClearCachePage() {
  const router = useRouter();
  const [cleared, setCleared] = useState(false);

  const handleClearCache = () => {
    // Clear all localStorage
    localStorage.clear();
    
    // Clear all sessionStorage
    sessionStorage.clear();
    
    setCleared(true);
    
    // Redirect to home after a short delay
    setTimeout(() => {
      router.push("/");
    }, 1500);
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center p-8">
      <div className="max-w-md space-y-6 text-center">
        <h1 className="text-3xl font-bold">Clear Browser Cache</h1>
        
        {!cleared ? (
          <>
            <p className="text-muted-foreground">
              If you're experiencing issues with the application, clearing the browser cache
              can help resolve them. This will reset all stored preferences and state.
            </p>
            <Button onClick={handleClearCache} size="lg">
              Clear Cache & Reload
            </Button>
          </>
        ) : (
          <div className="space-y-4">
            <p className="text-green-600 font-semibold">✓ Cache cleared successfully!</p>
            <p className="text-sm text-muted-foreground">Redirecting...</p>
          </div>
        )}
      </div>
    </div>
  );
}
