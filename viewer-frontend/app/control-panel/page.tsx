'use client';

import { useEffect, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { 
  Activity, 
  Server, 
  FileText, 
  Clock, 
  CheckCircle2, 
  XCircle,
  PlayCircle,
  StopCircle,
  RefreshCw,
  AlertCircle,
  Cpu,
  HardDrive,
  MemoryStick
} from 'lucide-react';
import WorkersPanel from '@/components/control-panel/WorkersPanel';
import JobsPanel from '@/components/control-panel/JobsPanel';
import TasksPanel from '@/components/control-panel/TasksPanel';
import SystemMetrics from '@/components/control-panel/SystemMetrics';

interface SystemStatus {
  timestamp: string;
  redis: string;
  workers: {
    count: number;
    status: string;
  };
  queues: Record<string, { active: number; reserved: number }>;
  metrics: {
    cpu_percent: number;
    memory_percent: number;
    disk_percent: number;
  };
}

export default function ControlPanelPage() {
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const fetchSystemStatus = async () => {
    try {
      const response = await fetch('http://localhost:8000/api/system/status');
      const data = await response.json();
      setSystemStatus(data);
      setLoading(false);
    } catch (error) {
      console.error('Failed to fetch system status:', error);
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSystemStatus();
    
    if (autoRefresh) {
      const interval = setInterval(fetchSystemStatus, 5000); // Refresh every 5 seconds
      return () => clearInterval(interval);
    }
  }, [autoRefresh]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="flex flex-col items-center gap-4">
          <RefreshCw className="h-8 w-8 animate-spin text-blue-500" />
          <p className="text-sm text-gray-500">Loading control panel...</p>
        </div>
      </div>
    );
  }

  const redisOnline = systemStatus?.redis === 'online';
  const workersOnline = (systemStatus?.workers.count ?? 0) > 0;
  const totalQueueTasks = Object.values(systemStatus?.queues || {}).reduce(
    (sum, q) => sum + q.active + q.reserved, 0
  );

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-950 dark:to-slate-900">
      {/* Header */}
      <div className="border-b bg-white/50 dark:bg-slate-900/50 backdrop-blur-sm">
        <div className="container mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
                OCR Pipeline Control Panel
              </h1>
              <p className="text-sm text-gray-500 mt-1">
                Monitor and control your document processing infrastructure
              </p>
            </div>
            
            <div className="flex items-center gap-3">
              <Button
                variant={autoRefresh ? 'default' : 'outline'}
                size="sm"
                onClick={() => setAutoRefresh(!autoRefresh)}
              >
                <Activity className="h-4 w-4 mr-2" />
                {autoRefresh ? 'Live' : 'Paused'}
              </Button>
              
              <Button
                variant="outline"
                size="sm"
                onClick={fetchSystemStatus}
              >
                <RefreshCw className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      </div>

      <div className="container mx-auto px-6 py-6">
        {/* Status Overview Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          {/* Redis Status */}
          <Card className="border-l-4 border-l-blue-500">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Server className="h-4 w-4" />
                Redis
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between">
                <div className="text-2xl font-bold">
                  {redisOnline ? (
                    <Badge variant="default" className="bg-green-500">
                      <CheckCircle2 className="h-3 w-3 mr-1" />
                      Online
                    </Badge>
                  ) : (
                    <Badge variant="destructive">
                      <XCircle className="h-3 w-3 mr-1" />
                      Offline
                    </Badge>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Workers Status */}
          <Card className="border-l-4 border-l-purple-500">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Cpu className="h-4 w-4" />
                Workers
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between">
                <div className="text-2xl font-bold">
                  {systemStatus?.workers.count || 0}
                </div>
                {workersOnline ? (
                  <Badge variant="default" className="bg-green-500">Active</Badge>
                ) : (
                  <Badge variant="secondary">Stopped</Badge>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Queue Tasks */}
          <Card className="border-l-4 border-l-orange-500">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Clock className="h-4 w-4" />
                Queue Tasks
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between">
                <div className="text-2xl font-bold">{totalQueueTasks}</div>
                <Badge variant="outline">
                  {Object.keys(systemStatus?.queues || {}).length} queues
                </Badge>
              </div>
            </CardContent>
          </Card>

          {/* System Health */}
          <Card className="border-l-4 border-l-emerald-500">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Activity className="h-4 w-4" />
                System Health
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between">
                <div className="text-2xl font-bold">
                  {redisOnline && workersOnline ? (
                    <Badge variant="default" className="bg-green-500">Healthy</Badge>
                  ) : (
                    <Badge variant="destructive">Degraded</Badge>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* System Metrics */}
        {systemStatus?.metrics && (
          <SystemMetrics metrics={systemStatus.metrics} />
        )}

        {/* Main Content Tabs */}
        <Tabs defaultValue="workers" className="space-y-4">
          <TabsList className="grid w-full grid-cols-3 lg:w-[400px]">
            <TabsTrigger value="workers">Workers</TabsTrigger>
            <TabsTrigger value="jobs">Jobs</TabsTrigger>
            <TabsTrigger value="tasks">Tasks</TabsTrigger>
          </TabsList>

          <TabsContent value="workers" className="space-y-4">
            <WorkersPanel />
          </TabsContent>

          <TabsContent value="jobs" className="space-y-4">
            <JobsPanel />
          </TabsContent>

          <TabsContent value="tasks" className="space-y-4">
            <TasksPanel />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
