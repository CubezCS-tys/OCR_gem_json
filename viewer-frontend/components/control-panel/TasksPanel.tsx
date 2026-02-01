'use client';

import { useState, useEffect } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { 
  ListChecks, 
  CheckCircle2, 
  Clock, 
  XCircle, 
  AlertCircle,
  RefreshCw,
  Search,
  Trash2
} from 'lucide-react';
import { toast } from 'sonner';

interface Task {
  task_id: string;
  name: string;
  state: string;
  worker?: string;
  args?: any[];
  kwargs?: Record<string, any>;
  eta?: string;
}

export default function TasksPanel() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTaskId, setSearchTaskId] = useState('');
  const [searchResult, setSearchResult] = useState<any>(null);
  const [searching, setSearching] = useState(false);

  const fetchTasks = async () => {
    try {
      const response = await fetch('http://localhost:8000/api/tasks');
      const data = await response.json();
      setTasks(data.tasks || []);
      setLoading(false);
    } catch (error) {
      console.error('Failed to fetch tasks:', error);
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTasks();
    const interval = setInterval(fetchTasks, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleSearchTask = async () => {
    if (!searchTaskId.trim()) {
      toast.error('Please enter a task ID');
      return;
    }

    setSearching(true);
    try {
      const response = await fetch(`http://localhost:8000/api/tasks/${searchTaskId}`);
      const data = await response.json();
      
      if (response.ok) {
        setSearchResult(data);
      } else {
        toast.error(`Task not found: ${data.detail}`);
      }
    } catch (error) {
      toast.error('Failed to search task');
    } finally {
      setSearching(false);
    }
  };

  const handleRevokeTask = async (taskId: string) => {
    try {
      const response = await fetch(`http://localhost:8000/api/tasks/${taskId}`, {
        method: 'DELETE'
      });
      
      if (response.ok) {
        toast.success('Task revoked');
        fetchTasks();
      } else {
        toast.error('Failed to revoke task');
      }
    } catch (error) {
      toast.error('Failed to revoke task');
    }
  };

  const getStateColor = (state: string) => {
    switch (state.toUpperCase()) {
      case 'SUCCESS':
        return 'bg-green-500';
      case 'ACTIVE':
      case 'STARTED':
        return 'bg-blue-500';
      case 'PENDING':
      case 'RESERVED':
      case 'SCHEDULED':
        return 'bg-yellow-500';
      case 'FAILURE':
      case 'REVOKED':
        return 'bg-red-500';
      default:
        return 'bg-gray-500';
    }
  };

  const getStateIcon = (state: string) => {
    switch (state.toUpperCase()) {
      case 'SUCCESS':
        return <CheckCircle2 className="h-4 w-4" />;
      case 'ACTIVE':
      case 'STARTED':
        return <RefreshCw className="h-4 w-4 animate-spin" />;
      case 'PENDING':
      case 'RESERVED':
      case 'SCHEDULED':
        return <Clock className="h-4 w-4" />;
      case 'FAILURE':
      case 'REVOKED':
        return <XCircle className="h-4 w-4" />;
      default:
        return <AlertCircle className="h-4 w-4" />;
    }
  };

  return (
    <div className="space-y-4">
      {/* Task Search */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Search className="h-5 w-5" />
            Search Task Status
          </CardTitle>
          <CardDescription>
            Enter a task ID to check its current status
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex gap-2">
            <Input
              placeholder="Enter task ID..."
              value={searchTaskId}
              onChange={(e) => setSearchTaskId(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearchTask()}
            />
            <Button onClick={handleSearchTask} disabled={searching}>
              {searching ? (
                <RefreshCw className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
            </Button>
          </div>

          {searchResult && (
            <div className="mt-4 p-4 border rounded-lg bg-slate-50 dark:bg-slate-900">
              <div className="flex items-center justify-between mb-3">
                <Badge className={getStateColor(searchResult.state)}>
                  {searchResult.state}
                </Badge>
                <span className="text-xs text-gray-500">
                  {searchResult.ready ? 'Complete' : 'In Progress'}
                </span>
              </div>
              
              <div className="space-y-2 text-sm">
                <div>
                  <span className="text-gray-500">Task ID:</span>
                  <p className="font-mono text-xs break-all">{searchResult.task_id}</p>
                </div>
                
                {searchResult.result && (
                  <div>
                    <span className="text-gray-500">Result:</span>
                    <pre className="mt-1 p-2 bg-slate-100 dark:bg-slate-800 rounded text-xs overflow-auto max-h-48">
                      {JSON.stringify(searchResult.result, null, 2)}
                    </pre>
                  </div>
                )}
                
                {searchResult.error && (
                  <div>
                    <span className="text-red-500">Error:</span>
                    <p className="text-red-600 text-xs mt-1">{searchResult.error}</p>
                  </div>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Active Tasks */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ListChecks className="h-5 w-5" />
            Active Tasks ({tasks.length})
          </CardTitle>
          <CardDescription>
            Currently running, pending, and scheduled tasks
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <RefreshCw className="h-6 w-6 animate-spin text-gray-400" />
            </div>
          ) : tasks.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <AlertCircle className="h-12 w-12 text-gray-300 mb-3" />
              <p className="text-sm text-gray-500">No active tasks</p>
              <p className="text-xs text-gray-400 mt-1">
                Submit a job to see tasks here
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {tasks.map((task) => (
                <div
                  key={task.task_id}
                  className="flex items-center justify-between p-4 border rounded-lg bg-slate-50 dark:bg-slate-900"
                >
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <div className={`h-10 w-10 rounded-full flex items-center justify-center ${getStateColor(task.state)} bg-opacity-20`}>
                      <div className="text-white">
                        {getStateIcon(task.state)}
                      </div>
                    </div>
                    
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <p className="font-medium text-sm truncate">
                          {task.name?.split('.').pop() || 'Unknown Task'}
                        </p>
                        <Badge className={getStateColor(task.state)}>
                          {task.state}
                        </Badge>
                      </div>
                      
                      <p className="text-xs text-gray-500 font-mono truncate">
                        {task.task_id}
                      </p>
                      
                      {task.worker && (
                        <p className="text-xs text-gray-400 mt-1">
                          Worker: {task.worker}
                        </p>
                      )}
                      
                      {task.args && task.args.length > 0 && (
                        <p className="text-xs text-gray-400 mt-1 truncate">
                          {String(task.args[0])}
                        </p>
                      )}
                    </div>
                  </div>
                  
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => handleRevokeTask(task.task_id)}
                    className="text-red-500 hover:text-red-700 hover:bg-red-50"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
