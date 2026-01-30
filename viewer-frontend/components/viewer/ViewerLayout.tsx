"use client";

import { useEffect, useState, useCallback, Component, ReactNode } from "react";
import { useViewerStore } from "@/lib/store";
import { FileSelector } from "./FileSelector";
import { ViewerHeader } from "./ViewerHeader";
import { ComparisonView } from "./ComparisonView";
import { EditorView } from "./EditorView";
import { PageThumbnails } from "./PageThumbnails";
import { toast } from "sonner";
import axios, { AxiosError } from "axios";
import { AlertTriangle, RefreshCw, FileQuestion } from "lucide-react";
import { Button } from "@/components/ui/button";

// Error Boundary Component
interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
  onReset?: () => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("ViewerLayout Error:", error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
    this.props.onReset?.();
  };

  render() {
    if (this.state.hasError) {
      return this.props.fallback || (
        <div className="flex items-center justify-center min-h-[400px] p-8">
          <div className="text-center max-w-md">
            <AlertTriangle className="h-12 w-12 text-destructive mx-auto mb-4" />
            <h3 className="text-lg font-semibold mb-2">Something went wrong</h3>
            <p className="text-sm text-muted-foreground mb-4">
              {this.state.error?.message || "An unexpected error occurred"}
            </p>
            <Button onClick={this.handleReset}>
              <RefreshCw className="h-4 w-4 mr-2" />
              Try Again
            </Button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

// Loading skeleton component
function LoadingSkeleton() {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mx-auto mb-4"></div>
        <p className="text-muted-foreground">Loading document...</p>
      </div>
    </div>
  );
}

// Empty state component
function EmptyState() {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center max-w-md p-8">
        <FileQuestion className="h-16 w-16 text-muted-foreground/50 mx-auto mb-4" />
        <h2 className="text-xl font-semibold mb-2">No Document Selected</h2>
        <p className="text-muted-foreground mb-6">
          Select a document to start viewing or editing OCR results.
        </p>
        <Button
          onClick={() => window.dispatchEvent(new CustomEvent('openFileSelector'))}
          size="lg"
        >
          Open Document
        </Button>
      </div>
    </div>
  );
}

// Retry helper with exponential backoff
async function fetchWithRetry<T>(
  fetchFn: () => Promise<T>,
  maxRetries: number = 3,
  delay: number = 1000
): Promise<T> {
  let lastError: Error | null = null;

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      return await fetchFn();
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));

      // Don't retry on client errors (4xx)
      if (err instanceof AxiosError && err.response?.status && err.response.status < 500) {
        throw err;
      }

      if (attempt < maxRetries - 1) {
        await new Promise(resolve => setTimeout(resolve, delay * Math.pow(2, attempt)));
      }
    }
  }

  throw lastError;
}

export function ViewerLayout() {
  const {
    viewMode,
    isLoading,
    error,
    setError,
    setAvailableFiles,
    setLoading,
    documentData,
    currentFile
  } = useViewerStore();

  const [retrying, setRetrying] = useState(false);

  const loadAvailableFiles = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await fetchWithRetry(() => axios.get("/api/files"));
      setAvailableFiles(response.data.files || []);
    } catch (err) {
      let message = "Failed to load files";

      if (err instanceof AxiosError) {
        if (err.response?.status === 404) {
          message = "Files directory not found. Check your configuration.";
        } else if (err.code === "ERR_NETWORK") {
          message = "Network error. Please check your connection.";
        } else if (err.response?.data?.error) {
          message = err.response.data.error;
        }
      } else if (err instanceof Error) {
        message = err.message;
      }

      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }, [setLoading, setError, setAvailableFiles]);

  // Load files on mount
  useEffect(() => {
    loadAvailableFiles();
  }, [loadAvailableFiles]);

  const handleRetry = async () => {
    setRetrying(true);
    await loadAvailableFiles();
    setRetrying(false);
  };

  // Error state
  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-background">
        <div className="text-center max-w-md p-8">
          <AlertTriangle className="h-16 w-16 text-destructive mx-auto mb-4" />
          <h2 className="text-2xl font-bold text-destructive mb-2">Error</h2>
          <p className="text-muted-foreground mb-6">{error}</p>
          <Button
            onClick={handleRetry}
            disabled={retrying}
            size="lg"
          >
            {retrying ? (
              <>
                <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                Retrying...
              </>
            ) : (
              <>
                <RefreshCw className="h-4 w-4 mr-2" />
                Retry
              </>
            )}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-background">
      {/* Header */}
      <ViewerHeader />

      {/* Main Content */}
      <div className="flex-1 overflow-hidden flex">
        {/* Page Thumbnails Sidebar - only show when document is loaded */}
        {documentData && (
          <PageThumbnails />
        )}

        {/* Main Viewing Area */}
        <div className="flex-1 overflow-hidden">
          <ErrorBoundary onReset={() => window.location.reload()}>
            {isLoading ? (
              <LoadingSkeleton />
            ) : !currentFile ? (
              <EmptyState />
            ) : viewMode === "comparison" ? (
              <ComparisonView />
            ) : (
              <EditorView />
            )}
          </ErrorBoundary>
        </div>
      </div>

      {/* File Selector Modal */}
      <FileSelector />
    </div>
  );
}
