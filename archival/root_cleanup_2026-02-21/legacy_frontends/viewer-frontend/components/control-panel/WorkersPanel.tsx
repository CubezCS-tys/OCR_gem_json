'use client';

import { useState, useEffect } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { 
  PlayCircle, 
  StopCircle, 
  RefreshCw, 
  Server,
  Activity,
  AlertCircle
} from 'lucide-react';
import { toast } from 'sonner';

interface Worker {
  name: string;
  status: string;
  pool: any;
  active_tasks: number;
  registered_tasks: number;
}

interface Process {
  pid: number;
  cmdline: string;
}

export default function WorkersPanel() {
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [processes, setProcesses] = useState<Process[]>([]);
  const [loading, setLoading] = useState(true);
  const [numWorkers, setNumWorkers] = useState(1);
  const [concurrency, setConcurrency] = useState(4);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fetchWorkers = async () => {
    try {
      const response = await fetch('http://localhost:8000/api/workers');
      const data = await response.json();
      setWorkers(data.workers || []);
      setProcesses(data.processes || []);
      setLoading(false);
    } catch (error) {
      console.error('Failed to fetch workers:', error);
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchWorkers();
    const interval = setInterval(fetchWorkers, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleStartWorkers = async () => {
    setActionLoading('start');
    try {
      const response = await fetch('http://localhost:8000/api/workers/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'start',
          num_workers: numWorkers,
          concurrency: concurrency,
          queues: ['celery', 'pdf_processing', 'html_rebuild']
        })
      });
      
      if (response.ok) {
        toast.success('Workers started successfully');
        setTimeout(fetchWorkers, 2000);
      } else {
        const error = await response.json();
        toast.error(`Failed to start workers: ${error.detail}`);
      }
    } catch (error) {
      toast.error('Failed to start workers');
    } finally {
      setActionLoading(null);
    }
  };

  const handleStopWorkers = async () => {
    setActionLoading('stop');
    try {
      const response = await fetch('http://localhost:8000/api/workers/stop', {
        method: 'POST'
      });
      
      if (response.ok) {
        toast.success('Workers stopped successfully');
        setTimeout(fetchWorkers, 2000);
      } else {
        toast.error('Failed to stop workers');
      }
    } catch (error) {
      toast.error('Failed to stop workers');
    } finally {
      setActionLoading(null);
    }
  };

  const handleRestartWorkers = async () => {
    setActionLoading('restart');
    try {
      const response = await fetch('http://localhost:8000/api/workers/restart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'restart',
          num_workers: numWorkers,
          concurrency: concurrency,
          queues: ['celery', 'pdf_processing', 'html_rebuild']
        })
      });
      
      if (response.ok) {
        toast.success('Workers restarted successfully');
        setTimeout(fetchWorkers, 2000);
      } else {
        toast.error('Failed to restart workers');
      }
    } catch (error) {
      toast.error('Failed to restart workers');
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <div className="space-y-4">
      {/* Control Panel */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="h-5 w-5" />
            Worker Control
          </CardTitle>
          <CardDescription>
            Start, stop, or restart Celery workers
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="num-workers">Number of Workers</Label>
                <Input
                  id="num-workers"
                  type="number"
                  min="1"
                  max="16"
                  value={numWorkers}
                  onChange={(e) => setNumWorkers(parseInt(e.target.value) || 1)}
                  className="mt-1"
                />
                <p className="text-xs text-gray-500 mt-1">
                  Separate worker processes (1-16)
                </p>
              </div>
              
              <div>
                <Label htmlFor="concurrency">Concurrency per Worker</Label>
                <Input
                  id="concurrency"
                  type="number"
                  min="1"
                  max="16"
                  value={concurrency}
                  onChange={(e) => setConcurrency(parseInt(e.target.value) || 1)}
                  className="mt-1"
                />
                <p className="text-xs text-gray-500 mt-1">
                  Tasks per worker (1-16)
                </p>
              </div>
            </div>
            
            <div className="bg-blue-50 dark:bg-blue-900/20 p-3 rounded-lg">
              <p className="text-sm font-medium text-blue-900 dark:text-blue-100">
                Total Capacity: {numWorkers * concurrency} parallel tasks
              </p>
              <p className="text-xs text-blue-700 dark:text-blue-300 mt-1">
                {numWorkers} worker{numWorkers > 1 ? 's' : ''} × {concurrency} concurrency = {numWorkers * concurrency} total
              </p>
            </div>
            
            <div className="flex gap-2">
              <Button
                onClick={handleStartWorkers}
                disabled={actionLoading !== null || workers.length > 0}
                className="bg-green-600 hover:bg-green-700"
              >
                  {actionLoading === 'start' ? (
                    <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <PlayCircle className="h-4 w-4 mr-2" />
                  )}
                  Start
                </Button>
                
                <Button
                  onClick={handleStopWorkers}
                  disabled={actionLoading !== null || workers.length === 0}
                  variant="destructive"
                >
                  {actionLoading === 'stop' ? (
                    <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <StopCircle className="h-4 w-4 mr-2" />
                  )}
                  Stop
                </Button>
                
                <Button
                  onClick={handleRestartWorkers}
                  disabled={actionLoading !== null}
                  variant="outline"
                >
                  {actionLoading === 'restart' ? (
                    <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <RefreshCw className="h-4 w-4 mr-2" />
                  )}
                  Restart
                </Button>
              </div>
          </div>
        </CardContent>
      </Card>

      {/* Active Workers */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5" />
            Active Workers ({workers.length})
          </CardTitle>
          <CardDescription>
            Currently running Celery workers and their status
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <RefreshCw className="h-6 w-6 animate-spin text-gray-400" />
            </div>
          ) : workers.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <AlertCircle className="h-12 w-12 text-gray-300 mb-3" />
              <p className="text-sm text-gray-500">No workers are currently running</p>
              <p className="text-xs text-gray-400 mt-1">
                Click &quot;Start&quot; to launch workers
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {workers.map((worker, index) => (
                <div
                  key={index}
                  className="flex items-center justify-between p-4 border rounded-lg bg-slate-50 dark:bg-slate-900"
                >
                  <div className="flex items-center gap-3">
                    <div className="h-10 w-10 rounded-full bg-green-100 dark:bg-green-900 flex items-center justify-center">
                      <Server className="h-5 w-5 text-green-600 dark:text-green-400" />
                    </div>
                    <div>
                      <p className="font-medium text-sm">{worker.name}</p>
                      <div className="flex items-center gap-2 mt-1">
                        <Badge variant="outline" className="text-xs">
                          {worker.active_tasks} active
                        </Badge>
                        <Badge variant="outline" className="text-xs">
                          {worker.registered_tasks} registered
                        </Badge>
                      </div>
                    </div>
                  </div>
                  <Badge className="bg-green-500">
                    {worker.status}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Worker Processes */}
      {processes.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Worker Processes</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {processes.map((proc, index) => (
                <div key={index} className="flex items-center justify-between text-sm p-2 border rounded bg-slate-50 dark:bg-slate-900">
                  <span className="font-mono text-xs text-gray-600 dark:text-gray-400">
                    PID: {proc.pid}
                  </span>
                  <span className="text-xs text-gray-500 truncate max-w-md">
                    {proc.cmdline}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
