'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Cpu, HardDrive, MemoryStick } from 'lucide-react';

interface SystemMetricsProps {
  metrics: {
    cpu_percent: number;
    memory_percent: number;
    disk_percent: number;
  };
}
//
export default function SystemMetrics({ metrics }: SystemMetricsProps) {
  const getColorClass = (percent: number) => {
    if (percent >= 90) return 'bg-red-500';
    if (percent >= 75) return 'bg-orange-500';
    if (percent >= 50) return 'bg-yellow-500';
    return 'bg-green-500';
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      {/* CPU Usage */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Cpu className="h-4 w-4" />
            CPU Usage
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-2xl font-bold">{metrics.cpu_percent.toFixed(1)}%</span>
              <span className={`text-xs px-2 py-1 rounded ${
                metrics.cpu_percent >= 75 ? 'bg-red-100 text-red-700' : 
                metrics.cpu_percent >= 50 ? 'bg-yellow-100 text-yellow-700' : 
                'bg-green-100 text-green-700'
              }`}>
                {metrics.cpu_percent >= 75 ? 'High' : 
                 metrics.cpu_percent >= 50 ? 'Medium' : 'Normal'}
              </span>
            </div>
            <Progress 
              value={metrics.cpu_percent} 
              className="h-2"
              indicatorClassName={getColorClass(metrics.cpu_percent)}
            />
          </div>
        </CardContent>
      </Card>

      {/* Memory Usage */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <MemoryStick className="h-4 w-4" />
            Memory Usage
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-2xl font-bold">{metrics.memory_percent.toFixed(1)}%</span>
              <span className={`text-xs px-2 py-1 rounded ${
                metrics.memory_percent >= 90 ? 'bg-red-100 text-red-700' : 
                metrics.memory_percent >= 75 ? 'bg-yellow-100 text-yellow-700' : 
                'bg-green-100 text-green-700'
              }`}>
                {metrics.memory_percent >= 90 ? 'Critical' : 
                 metrics.memory_percent >= 75 ? 'High' : 'Normal'}
              </span>
            </div>
            <Progress 
              value={metrics.memory_percent} 
              className="h-2"
              indicatorClassName={getColorClass(metrics.memory_percent)}
            />
          </div>
        </CardContent>
      </Card>

      {/* Disk Usage */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <HardDrive className="h-4 w-4" />
            Disk Usage
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-2xl font-bold">{metrics.disk_percent.toFixed(1)}%</span>
              <span className={`text-xs px-2 py-1 rounded ${
                metrics.disk_percent >= 90 ? 'bg-red-100 text-red-700' : 
                metrics.disk_percent >= 75 ? 'bg-yellow-100 text-yellow-700' : 
                'bg-green-100 text-green-700'
              }`}>
                {metrics.disk_percent >= 90 ? 'Critical' : 
                 metrics.disk_percent >= 75 ? 'High' : 'Normal'}
              </span>
            </div>
            <Progress 
              value={metrics.disk_percent} 
              className="h-2"
              indicatorClassName={getColorClass(metrics.disk_percent)}
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
