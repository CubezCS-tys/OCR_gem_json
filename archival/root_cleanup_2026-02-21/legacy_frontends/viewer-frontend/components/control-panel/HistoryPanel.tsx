'use client';

import { useEffect, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Clock,
  FileText,
  FolderOpen,
  TrendingUp,
  Activity,
  CheckCircle2,
  XCircle,
  RefreshCw,
  AlertCircle,
  BarChart3,
  Calendar,
  DollarSign,
  Timer,
  AlertTriangle
} from 'lucide-react';

interface JobHistory {
  job_id: string;
  task_id?: string;
  type: string;
  pdf_name: string;
  pdf_path: string;
  priority: string;
  format: string;
  status: string;
  submitted_at: number;
  submitted_at_iso: string;
  current_state?: string;
}

interface BatchHistory {
  batch_id: string;
  type: string;
  directory: string;
  pattern: string;
  total_files: number;
  submitted: number;
  cached: number;
  priority?: string;
  status: string;
  submitted_at: number;
  submitted_at_iso: string;
}

interface Statistics {
  total_jobs: number;
  total_batches: number;
  total_files_processed: number;
  jobs_by_status: Record<string, number>;
  jobs_by_priority: Record<string, number>;
  recent_activity: Array<{
    type: string;
    id: string;
    name: string;
    status: string;
    timestamp: string;
  }>;
  cache_hit_rate: number;
  total_cost_usd: number;
  average_processing_time: number;
  total_processing_time: number;
  failed_jobs: number;
  retry_count: number;
}

export default function HistoryPanel() {
  const [jobs, setJobs] = useState<JobHistory[]>([]);
  const [batches, setBatches] = useState<BatchHistory[]>([]);
  const [statistics, setStatistics] = useState<Statistics | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('statistics');

  const fetchHistory = async () => {
    try {
      const [jobsRes, batchesRes, statsRes] = await Promise.all([
        fetch('http://localhost:8000/api/history/jobs?limit=50'),
        fetch('http://localhost:8000/api/history/batches?limit=50'),
        fetch('http://localhost:8000/api/history/statistics')
      ]);

      const jobsData = await jobsRes.json();
      const batchesData = await batchesRes.json();
      const statsData = await statsRes.json();

      setJobs(jobsData.jobs || []);
      setBatches(batchesData.batches || []);
      setStatistics(statsData);
      setLoading(false);
    } catch (error) {
      console.error('Failed to fetch history:', error);
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHistory();
    const interval = setInterval(fetchHistory, 10000); // Refresh every 10 seconds
    return () => clearInterval(interval);
  }, []);

  const getStatusBadge = (status: string, state?: string) => {
    const displayStatus = state || status;
    
    switch (displayStatus?.toUpperCase()) {
      case 'SUCCESS':
      case 'COMPLETED':
        return <Badge className="bg-green-500"><CheckCircle2 className="h-3 w-3 mr-1" />Success</Badge>;
      case 'FAILURE':
      case 'FAILED':
        return <Badge variant="destructive"><XCircle className="h-3 w-3 mr-1" />Failed</Badge>;
      case 'PENDING':
      case 'SUBMITTED':
        return <Badge variant="secondary"><Clock className="h-3 w-3 mr-1" />Pending</Badge>;
      case 'STARTED':
      case 'PROGRESS':
        return <Badge className="bg-blue-500"><Activity className="h-3 w-3 mr-1" />Running</Badge>;
      case 'CACHED':
        return <Badge className="bg-purple-500"><CheckCircle2 className="h-3 w-3 mr-1" />Cached</Badge>;
      default:
        return <Badge variant="outline">{displayStatus}</Badge>;
    }
  };

  const getPriorityBadge = (priority: string) => {
    const colors: Record<string, string> = {
      urgent: 'bg-red-500',
      high: 'bg-orange-500',
      normal: 'bg-blue-500',
      low: 'bg-gray-500'
    };
    return <Badge className={colors[priority] || 'bg-gray-500'}>{priority}</Badge>;
  };

  const formatTimestamp = (isoString: string) => {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
  };

  if (loading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center p-8">
          <RefreshCw className="h-6 w-6 animate-spin text-blue-500 mr-2" />
          <span>Loading history...</span>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {/* Statistics Overview */}
      {statistics && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <Card className="border-l-4 border-l-blue-500">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium flex items-center gap-2">
                  <FileText className="h-4 w-4" />
                  Total Jobs
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{statistics.total_jobs}</div>
                <p className="text-xs text-gray-500 mt-1">Individual job submissions</p>
              </CardContent>
            </Card>

            <Card className="border-l-4 border-l-purple-500">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium flex items-center gap-2">
                  <FolderOpen className="h-4 w-4" />
                  Total Batches
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{statistics.total_batches}</div>
                <p className="text-xs text-gray-500 mt-1">Batch job submissions</p>
              </CardContent>
            </Card>

            <Card className="border-l-4 border-l-green-500">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium flex items-center gap-2">
                  <BarChart3 className="h-4 w-4" />
                  Files Processed
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{statistics.total_files_processed}</div>
                <p className="text-xs text-gray-500 mt-1">Total PDF files</p>
              </CardContent>
            </Card>

            <Card className="border-l-4 border-l-orange-500">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium flex items-center gap-2">
                  <TrendingUp className="h-4 w-4" />
                  Cache Hit Rate
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{statistics.cache_hit_rate}%</div>
                <p className="text-xs text-gray-500 mt-1">Cached results reused</p>
              </CardContent>
            </Card>
          </div>

          {/* Additional Metrics Row */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <Card className="border-l-4 border-l-emerald-500">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium flex items-center gap-2">
                  <DollarSign className="h-4 w-4" />
                  Total Cost
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">${statistics.total_cost_usd.toFixed(4)}</div>
                <p className="text-xs text-gray-500 mt-1">API costs (USD)</p>
              </CardContent>
            </Card>

            <Card className="border-l-4 border-l-cyan-500">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium flex items-center gap-2">
                  <Timer className="h-4 w-4" />
                  Avg Processing Time
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{statistics.average_processing_time.toFixed(1)}s</div>
                <p className="text-xs text-gray-500 mt-1">Per job average</p>
              </CardContent>
            </Card>

            <Card className="border-l-4 border-l-yellow-500">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium flex items-center gap-2">
                  <Clock className="h-4 w-4" />
                  Total Time
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{Math.floor(statistics.total_processing_time / 60)}m</div>
                <p className="text-xs text-gray-500 mt-1">{statistics.total_processing_time.toFixed(0)}s total</p>
              </CardContent>
            </Card>

            <Card className="border-l-4 border-l-red-500">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4" />
                  Failed Jobs
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{statistics.failed_jobs}</div>
                <p className="text-xs text-gray-500 mt-1">Errors encountered</p>
              </CardContent>
            </Card>
          </div>
        </>
      )}

      {/* Main Content */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-xl flex items-center gap-2">
                <Calendar className="h-5 w-5" />
                Execution History
              </CardTitle>
              <CardDescription>View past job and batch submissions with detailed statistics</CardDescription>
            </div>
            <Button variant="outline" size="sm" onClick={fetchHistory}>
              <RefreshCw className="h-4 w-4 mr-2" />
              Refresh
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="grid w-full grid-cols-3">
              <TabsTrigger value="statistics">Statistics</TabsTrigger>
              <TabsTrigger value="jobs">Jobs ({jobs.length})</TabsTrigger>
              <TabsTrigger value="batches">Batches ({batches.length})</TabsTrigger>
            </TabsList>

            {/* Statistics Tab */}
            <TabsContent value="statistics" className="space-y-4 mt-4">
              {statistics && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Jobs by Status */}
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">Jobs by Status</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-2">
                        {Object.entries(statistics.jobs_by_status).map(([status, count]) => (
                          <div key={status} className="flex items-center justify-between py-2 border-b last:border-0">
                            <div className="flex items-center gap-2">
                              {getStatusBadge(status)}
                              <span className="text-sm capitalize">{status}</span>
                            </div>
                            <span className="font-semibold">{count}</span>
                          </div>
                        ))}
                        {Object.keys(statistics.jobs_by_status).length === 0 && (
                          <p className="text-sm text-gray-500 text-center py-4">No data available</p>
                        )}
                      </div>
                    </CardContent>
                  </Card>

                  {/* Jobs by Priority */}
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">Jobs by Priority</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-2">
                        {Object.entries(statistics.jobs_by_priority).map(([priority, count]) => (
                          <div key={priority} className="flex items-center justify-between py-2 border-b last:border-0">
                            <div className="flex items-center gap-2">
                              {getPriorityBadge(priority)}
                              <span className="text-sm capitalize">{priority}</span>
                            </div>
                            <span className="font-semibold">{count}</span>
                          </div>
                        ))}
                        {Object.keys(statistics.jobs_by_priority).length === 0 && (
                          <p className="text-sm text-gray-500 text-center py-4">No data available</p>
                        )}
                      </div>
                    </CardContent>
                  </Card>

                  {/* Recent Activity */}
                  <Card className="md:col-span-2">
                    <CardHeader>
                      <CardTitle className="text-base">Recent Activity</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-2">
                        {statistics.recent_activity.map((activity) => (
                          <div key={activity.id} className="flex items-center justify-between py-3 border-b last:border-0">
                            <div className="flex items-center gap-3">
                              {activity.type === 'job' ? (
                                <FileText className="h-4 w-4 text-blue-500" />
                              ) : (
                                <FolderOpen className="h-4 w-4 text-purple-500" />
                              )}
                              <div>
                                <div className="font-medium text-sm">{activity.name}</div>
                                <div className="text-xs text-gray-500">{activity.type} • {formatTimestamp(activity.timestamp)}</div>
                              </div>
                            </div>
                            {getStatusBadge(activity.status)}
                          </div>
                        ))}
                        {statistics.recent_activity.length === 0 && (
                          <p className="text-sm text-gray-500 text-center py-4">No recent activity</p>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                </div>
              )}
            </TabsContent>

            {/* Jobs Tab */}
            <TabsContent value="jobs" className="mt-4">
              <div className="space-y-3">
                {jobs.length === 0 ? (
                  <div className="text-center py-8 text-gray-500">
                    <FileText className="h-12 w-12 mx-auto mb-2 opacity-50" />
                    <p>No job history available</p>
                  </div>
                ) : (
                  jobs.map((job) => (
                    <Card key={job.job_id} className="hover:shadow-md transition-shadow">
                      <CardContent className="p-4">
                        <div className="flex items-start justify-between">
                          <div className="flex-1">
                            <div className="flex items-center gap-2 mb-2">
                              <FileText className="h-4 w-4 text-blue-500" />
                              <span className="font-medium">{job.pdf_name}</span>
                              {getPriorityBadge(job.priority)}
                            </div>
                            <div className="grid grid-cols-2 gap-2 text-sm text-gray-600">
                              <div>
                                <span className="text-gray-400">Path:</span> {job.pdf_path}
                              </div>
                              <div>
                                <span className="text-gray-400">Format:</span> {job.format}
                              </div>
                              <div>
                                <span className="text-gray-400">Task ID:</span> {job.task_id?.substring(0, 8)}...
                              </div>
                              <div>
                                <span className="text-gray-400">Submitted:</span> {formatTimestamp(job.submitted_at_iso)}
                              </div>
                              {(job as any).processing_time && (
                                <div className="flex items-center gap-1">
                                  <Timer className="h-3 w-3 text-gray-400" />
                                  <span className="text-gray-400">Time:</span> {(job as any).processing_time.toFixed(2)}s
                                </div>
                              )}
                              {(job as any).cost && (
                                <div className="flex items-center gap-1">
                                  <DollarSign className="h-3 w-3 text-gray-400" />
                                  <span className="text-gray-400">Cost:</span> ${(job as any).cost.total_cost_usd.toFixed(4)}
                                </div>
                              )}
                              {(job as any).cached && (
                                <div className="col-span-2">
                                  <Badge variant="outline" className="bg-purple-50">
                                    <CheckCircle2 className="h-3 w-3 mr-1" />
                                    Result from cache
                                  </Badge>
                                </div>
                              )}
                              {(job as any).error && (
                                <div className="col-span-2 text-red-600 text-xs">
                                  <AlertTriangle className="h-3 w-3 inline mr-1" />
                                  {(job as any).error}
                                </div>
                              )}
                            </div>
                          </div>
                          <div className="ml-4">
                            {getStatusBadge(job.status, job.current_state)}
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  ))
                )}
              </div>
            </TabsContent>

            {/* Batches Tab */}
            <TabsContent value="batches" className="mt-4">
              <div className="space-y-3">
                {batches.length === 0 ? (
                  <div className="text-center py-8 text-gray-500">
                    <FolderOpen className="h-12 w-12 mx-auto mb-2 opacity-50" />
                    <p>No batch history available</p>
                  </div>
                ) : (
                  batches.map((batch) => (
                    <Card key={batch.batch_id} className="hover:shadow-md transition-shadow">
                      <CardContent className="p-4">
                        <div className="flex items-start justify-between">
                          <div className="flex-1">
                            <div className="flex items-center gap-2 mb-2">
                              <FolderOpen className="h-4 w-4 text-purple-500" />
                              <span className="font-medium">{batch.directory}</span>
                            </div>
                            <div className="grid grid-cols-2 gap-2 text-sm text-gray-600">
                              <div>
                                <span className="text-gray-400">Pattern:</span> {batch.pattern}
                              </div>
                              <div>
                                <span className="text-gray-400">Total Files:</span> {batch.total_files}
                              </div>
                              <div>
                                <span className="text-gray-400">Submitted:</span> {batch.submitted}
                              </div>
                              <div>
                                <span className="text-gray-400">Cached:</span> {batch.cached}
                              </div>
                              <div>
                                <span className="text-gray-400">Priority:</span> {getPriorityBadge(batch.priority || 'normal')}
                              </div>
                              <div>
                                <span className="text-gray-400">Time:</span> {formatTimestamp(batch.submitted_at_iso)}
                              </div>
                            </div>
                          </div>
                          <div className="ml-4">
                            {getStatusBadge(batch.status)}
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  ))
                )}
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
}
