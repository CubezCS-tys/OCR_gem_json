"use client";

import { useRouter } from "next/navigation";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { FileText, Settings, LogOut } from "lucide-react";
import { toast } from "sonner";

export default function SelectPage() {
  const router = useRouter();

  const handleLogout = () => {
    toast.success("Logged out successfully");
    router.push("/login");
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-900 dark:to-slate-800">
      <div className="container mx-auto px-4 py-16">
        {/* Header with Logout */}
        <div className="flex justify-end mb-4">
          <Button
            variant="outline"
            onClick={handleLogout}
            className="gap-2"
          >
            <LogOut className="h-4 w-4" />
            Logout
          </Button>
        </div>

        {/* Header */}
        <div className="text-center mb-12">
          <h1 className="text-5xl font-bold mb-4 bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
            OCR Processing System
          </h1>
          <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
            Choose your destination
          </p>
        </div>

        {/* Navigation Cards */}
        <div className="max-w-4xl mx-auto grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Viewer Card */}
          <Card className="hover:shadow-xl transition-all duration-300 hover:scale-105 cursor-pointer border-2 hover:border-blue-500">
            <CardHeader>
              <div className="flex items-center gap-3 mb-2">
                <div className="p-3 bg-blue-100 dark:bg-blue-900 rounded-lg">
                  <FileText className="h-8 w-8 text-blue-600 dark:text-blue-400" />
                </div>
                <CardTitle className="text-2xl">Document Viewer</CardTitle>
              </div>
              <CardDescription className="text-base">
                View, compare, and edit processed OCR documents with an intuitive interface
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button 
                onClick={() => router.push("/viewer")} 
                className="w-full"
                size="lg"
              >
                Open Viewer
              </Button>
              <ul className="mt-4 space-y-2 text-sm text-muted-foreground">
                <li>• Side-by-side document comparison</li>
                <li>• Real-time editing and annotations</li>
                <li>• Export to multiple formats</li>
              </ul>
            </CardContent>
          </Card>

          {/* Control Panel Card */}
          <Card className="hover:shadow-xl transition-all duration-300 hover:scale-105 cursor-pointer border-2 hover:border-purple-500">
            <CardHeader>
              <div className="flex items-center gap-3 mb-2">
                <div className="p-3 bg-purple-100 dark:bg-purple-900 rounded-lg">
                  <Settings className="h-8 w-8 text-purple-600 dark:text-purple-400" />
                </div>
                <CardTitle className="text-2xl">Control Panel</CardTitle>
              </div>
              <CardDescription className="text-base">
                Monitor and manage OCR processing jobs, workers, and system resources
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button 
                onClick={() => router.push("/control-panel")} 
                className="w-full"
                size="lg"
                variant="secondary"
              >
                Open Control Panel
              </Button>
              <ul className="mt-4 space-y-2 text-sm text-muted-foreground">
                <li>• Real-time job monitoring</li>
                <li>• Worker management</li>
                <li>• System performance metrics</li>
              </ul>
            </CardContent>
          </Card>
        </div>

        {/* Footer */}
        <div className="text-center mt-12 text-sm text-muted-foreground">
          <p>OCR Processing System • Powered by Next.js & Celery</p>
        </div>
      </div>
    </div>
  );
}
